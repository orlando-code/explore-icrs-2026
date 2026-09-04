"""Parse and load the ICRS delegate list."""
from __future__ import annotations
import json
import re
import subprocess
from pathlib import Path
from typing import Any
import pandas as pd
import pycountry
from src.sources.programme import load_talks
from src.data_paths import DELEGATE_ORG_OVERRIDES_CSV, DELEGATE_PDF, DELEGATES_JSON, DELEGATES_LAYOUT_TXT
from src.util.json_io import load_json, save_json
DEFAULT_DELEGATE_PDF_PATH = DELEGATE_PDF
DEFAULT_DELEGATES_JSON_PATH = DELEGATES_JSON
DEFAULT_DELEGATES_LAYOUT_CACHE = DELEGATES_LAYOUT_TXT
DEFAULT_ORG_OVERRIDES_PATH = DELEGATE_ORG_OVERRIDES_CSV
_ORGANISATION_OVERRIDE_CACHE: dict[str, tuple[str, str]] | None = None
COL_FIRST = 4
COL_LAST = 32
COL_ORG = 57
COL_COUNTRY = 114
_COUNTRY_COL_MIN = 90
_ORG_COL_MIN = 45
TITLE_RE = re.compile('^(dr|prof|professor|mr|mrs|ms|miss)\\.?\\s+', re.IGNORECASE)
_MOJIBAKE_MARKERS_RE = re.compile('[√ÃÂ]')
COUNTRY_ALIASES = {'united states': 'United States', 'united kingdom': 'United Kingdom', 'hong kong': 'Hong Kong', 'french polynesia': 'French Polynesia', 'marshall islands': 'Marshall Islands', 'south korea': 'South Korea', 'korea, republic of': 'South Korea', 'republic of korea': 'South Korea', 'taiwan': 'Taiwan', 'russia': 'Russian Federation', 'vietnam': 'Viet Nam', 'bolivia': 'Bolivia, Plurinational State of', 'bolivia, plurinational state of': 'Bolivia, Plurinational State of', 'iran': 'Iran, Islamic Republic of', 'tanzania': 'Tanzania, United Republic of', 'tanzania, united republic of': 'Tanzania, United Republic of', 'venezuela': 'Venezuela, Bolivarian Republic of', 'venezuela, bolivarian republic of': 'Venezuela, Bolivarian Republic of', 'usa': 'United States', 'uk': 'United Kingdom', 'uae': 'United Arab Emirates', 'papua new guinea': 'Papua New Guinea', 'new zealand': 'New Zealand', 'saudi arabia': 'Saudi Arabia', 'south africa': 'South Africa', 'cook islands': 'Cook Islands', 'solomon islands': 'Solomon Islands', 'northern mariana islands': 'Northern Mariana Islands', 'northern mariana': 'Northern Mariana Islands', 'federated states of micronesia': 'Micronesia, Federated States of', 'micronesia': 'Micronesia, Federated States of', 'micronesia (the federated states of)': 'Micronesia, Federated States of', 'micronesia (the': 'Micronesia, Federated States of', 'virgin islands (u.s.)': 'United States Virgin Islands', 'virgin islands (us)': 'United States Virgin Islands', 'u.s. virgin islands': 'United States Virgin Islands', 'us virgin islands': 'United States Virgin Islands', 'united states virgin islands': 'United States Virgin Islands', 'sint maarten': 'Sint Maarten', 'nederland': 'Netherlands', 'netherlands': 'Netherlands', 'curaçao': 'Curaçao', 'curacao': 'Curaçao'}
_EXTRA_COUNTRY_NAMES = {'Hong Kong', 'Taiwan', 'New Zealand', 'United States', 'United Kingdom', 'United Arab Emirates', 'Papua New Guinea', 'French Polynesia', 'Saudi Arabia', 'South Africa', 'Cook Islands', 'Solomon Islands', 'Northern Mariana Islands', 'Micronesia, Federated States of', 'Federated States of Micronesia', 'South Korea', 'Korea, Republic of', 'Sint Maarten', 'United States Virgin Islands', 'Virgin Islands (U.S.)', 'American Samoa', 'Puerto Rico', 'Palau', 'Maldives', 'Mauritius', 'Seychelles', 'Vanuatu', 'Samoa', 'Fiji', 'Indonesia', 'Philippines', 'Australia', 'Japan', 'China', 'India', 'Brazil', 'Egypt', 'Israel', 'Germany', 'France', 'Canada', 'Mexico', 'Jamaica', 'Kenya', 'Madagascar', 'Malaysia', 'Singapore', 'Thailand', 'Viet Nam', 'Spain', 'Italy', 'Netherlands', 'Belgium', 'Switzerland', 'Sweden', 'Norway', 'Denmark', 'Finland', 'Ireland', 'Portugal', 'Greece', 'Poland', 'Austria', 'Czechia', 'Hungary', 'Romania', 'Turkey', 'Qatar', 'Kuwait', 'Oman', 'Bahrain', 'Jordan', 'Lebanon', 'Morocco', 'Tunisia', 'Nigeria', 'Ghana', 'Tanzania, United Republic of', 'South Sudan', 'Ethiopia', 'Mozambique', 'Zimbabwe', 'Botswana', 'Namibia', 'Zambia', 'Uganda', 'Rwanda', 'Cameroon', 'Senegal', 'Colombia', 'Ecuador', 'Peru', 'Chile', 'Argentina', 'Uruguay', 'Panama', 'Costa Rica', 'Honduras', 'Guatemala', 'Cuba', 'Dominican Republic', 'Trinidad and Tobago', 'Barbados', 'Bahamas', 'Belize', 'Guam', 'Hawaii, USA', 'Pohnpei, Federated States of Micronesia'}
_COUNTRY_SUFFIXES: list[str] | None = None
_ORG_HINT_RE = re.compile('\\b(?:university|institute|college|school|department|division|dept|center|centre|laboratory|laboratories|research|national|marine|sciences?|conservancy|foundation|ministry|agency|government|state of|cooperative|museum|corporation|corp|organization|organisation|limited|ltd|inc|consulting|studies|resources?|management|bureau|office|authority|commission|programme|program|unit|fund|academy|society|association|network|partners|group|company|tech|a&m)\\b', re.IGNORECASE)
_BLEED_NAME_RE = re.compile("^[A-Z][a-z'`-]+(?:\\s+[A-Z][a-z'`-]+){0,2}$")
_TITLE_TOKENS = frozenset({'dr', 'prof', 'professor', 'mr', 'mrs', 'ms', 'miss'})
_BLEED_TITLE_NAME_RE = re.compile('^(.*?)(?:\\s+(?:Dr|Prof|Professor|Mr|Mrs|Ms|Miss)\\.?\\s+[A-Z].*)$', re.IGNORECASE)
_INCOMPLETE_ORG_ENDINGS = frozenset({'of', 'the', 'and', 'for', 'at', 'in', 'de', 'du', 'la', 'le', '-', '&'})

def is_incomplete_organisation(name: str) -> bool:
    cleaned = str(name or '').strip()
    if not cleaned:
        return True
    if cleaned in {'.', '-', '—'}:
        return True
    if cleaned.casefold() in {'nan', 'national', 'lumpkin'}:
        return True
    if re.search('\\s/\\s*$', cleaned):
        return True
    if cleaned in ('University of', 'University of the'):
        return True
    last = cleaned.split()[-1].casefold().rstrip('.')
    if last in _INCOMPLETE_ORG_ENDINGS:
        return True
    parts = [part for part in cleaned.split() if part]
    return len(parts) == 3 and parts[0].casefold() == 'university' and (parts[1].casefold() == 'of') and (parts[2].casefold() in {'southern', 'northern', 'eastern', 'western', 'central', 'virgin', 'new', 'south', 'north', 'east', 'west'})

def _is_title_token(word: str) -> bool:
    return word.casefold().rstrip('.') in _TITLE_TOKENS

def _split_bleed_title_name(segment: str) -> str:
    """Drop a glued-on ``Dr Firstname …`` suffix from a merged PDF column."""
    match = _BLEED_TITLE_NAME_RE.match(segment.strip())
    if not match:
        return segment.strip()
    prefix = match.group(1).strip()
    if prefix and _ORG_HINT_RE.search(prefix):
        return prefix
    return segment.strip()

def _strip_trailing_title_only(segment: str) -> str:
    words = segment.split()
    while len(words) >= 2 and _is_title_token(words[-1]):
        words.pop()
    return ' '.join(words).strip()

def _segment_is_bleed_person_name(segment: str) -> bool:
    segment = segment.strip()
    if not segment or _ORG_HINT_RE.search(segment):
        return False
    words = segment.split()
    if len(words) > 3:
        return False
    if _BLEED_NAME_RE.match(segment):
        return True
    return len(words) == 1 and words[0][0].isupper() and (len(words[0]) > 2)

def _strip_trailing_bleed_name(segment: str, first_name: str, last_name: str, *, aggressive: bool=False) -> str:
    """Remove glued-on ``Dr Firstname …`` suffixes from a merged PDF column."""
    del aggressive
    del first_name, last_name
    original = re.sub('\\s+', ' ', segment).strip()
    segment = _split_bleed_title_name(original)
    return _strip_trailing_title_only(segment)

def sanitize_delegate_organisation(organisation: str, *, first_name: str='', last_name: str='', country: str='') -> str:
    """Extract the primary organisation when PDF columns bleed into each other."""
    raw = str(organisation or '').strip()
    if not raw:
        return ''
    if not re.search('\\s{2,}', raw):
        single = re.sub('\\s+', ' ', raw)
        result = _strip_trailing_bleed_name(single, first_name, last_name)
        if is_incomplete_organisation(result):
            return single
        return result
    segments = [part.strip() for part in re.split('\\s{2,}', raw) if part.strip()]
    country_fold = country.strip().casefold()
    cleaned: list[str] = []
    for segment in segments:
        if _segment_is_bleed_person_name(segment):
            continue
        if country_fold and segment.casefold() == country_fold:
            continue
        if country and segment in _known_country_suffixes():
            continue
        cleaned.append(_strip_trailing_bleed_name(segment, first_name, last_name, aggressive=bool(_BLEED_TITLE_NAME_RE.search(segment))))
    org_like = [segment for segment in cleaned if _ORG_HINT_RE.search(segment)]
    pick = (org_like or cleaned or [raw])[0]
    result = _strip_trailing_bleed_name(re.sub('\\s+', ' ', pick).strip(), first_name, last_name, aggressive=bool(_BLEED_TITLE_NAME_RE.search(pick)))
    if is_incomplete_organisation(result):
        fallback = re.sub('\\s+', ' ', raw).strip()
        fallback = _strip_trailing_title_only(_split_bleed_title_name(fallback))
        if fallback and (not is_incomplete_organisation(fallback)):
            return fallback
    return result

def load_organisation_overrides(path: Path=DEFAULT_ORG_OVERRIDES_PATH) -> dict[str, tuple[str, str]]:
    """Return manual delegate overrides keyed by normalized person name.

    Values are ``(organisation, country)``; country may be empty when unchanged.
    """
    global _ORGANISATION_OVERRIDE_CACHE
    if _ORGANISATION_OVERRIDE_CACHE is not None and path == DEFAULT_ORG_OVERRIDES_PATH:
        return _ORGANISATION_OVERRIDE_CACHE
    overrides: dict[str, tuple[str, str]] = {}
    if not path.exists():
        _ORGANISATION_OVERRIDE_CACHE = overrides
        return overrides
    frame = pd.read_csv(path)
    for _, row in frame.iterrows():
        organisation = str(row.get('organisation') or '').strip()
        if not organisation:
            continue
        country_raw = row.get('country')
        if pd.isna(country_raw):
            country = ''
        else:
            country = str(country_raw).strip()
        if country.casefold() in {'', 'nan', 'none'}:
            country = ''
        for name_column in ('full_name', 'name'):
            name = str(row.get(name_column) or '').strip()
            if not name:
                continue
            overrides[normalize_person_name(name)] = (organisation, country)
            overrides[name.casefold()] = (organisation, country)
    if path == DEFAULT_ORG_OVERRIDES_PATH:
        _ORGANISATION_OVERRIDE_CACHE = overrides
    return overrides

def delegate_override_for_row(row: pd.Series | dict[str, Any]) -> tuple[str, str] | None:
    if isinstance(row, pd.Series):
        row = row.to_dict()
    overrides = load_organisation_overrides()
    for key in (normalize_person_name(str(row.get('full_name') or '')), str(row.get('full_name') or '').strip().casefold(), normalize_person_name(str(row.get('presenter') or '')), str(row.get('presenter') or '').strip().casefold()):
        if key and key in overrides:
            return overrides[key]
    return None

def organisation_override_for_row(row: pd.Series | dict[str, Any]) -> str | None:
    override = delegate_override_for_row(row)
    if override:
        return override[0] or None
    return None

def country_override_for_row(row: pd.Series | dict[str, Any]) -> str | None:
    override = delegate_override_for_row(row)
    if not override:
        return None
    country = str(override[1] or '').strip()
    if country.casefold() in {'', 'nan', 'none'}:
        return None
    return country

def resolve_compound_org_country(organisation: str, country: str, *, data_dir: Path | str='data') -> tuple[str, str]:
    """Map compound affiliations to reviewed primary org + country."""
    organisation = str(organisation or '').strip()
    country = str(country or '').strip()
    if country.casefold() in {'', 'nan', 'none'}:
        country = ''
    if not organisation:
        return (organisation, country)
    from src.registry.affiliation_registry import _build_org_redirects, _resolve_attendee_org_country, load_affiliation_review
    reviews = load_affiliation_review()
    if reviews.empty:
        return (organisation, country)
    return _resolve_attendee_org_country(organisation, country, _build_org_redirects(reviews))

def resolve_compound_affiliation_string(affiliation: str, *, data_dir: Path | str='data') -> str:
    """Return affiliation text with compound orgs mapped to reviewed primary."""
    from src.registry.affiliation_registry import parse_affiliation_parts
    organisation, country = parse_affiliation_parts(str(affiliation or ''))
    organisation, country = resolve_compound_org_country(organisation, country, data_dir=data_dir)
    if organisation and country:
        return f'{organisation}, {country}'
    return organisation or str(affiliation or '').strip()

def delegate_country_for_row(row: pd.Series | dict[str, Any], *, apply_overrides: bool=True) -> str:
    if isinstance(row, pd.Series):
        row = row.to_dict()
    if apply_overrides:
        override = country_override_for_row(row)
        if override:
            return override
    raw_country = row.get('country')
    if pd.isna(raw_country):
        return ''
    country = str(raw_country or '').strip()
    if country.casefold() in {'', 'nan', 'none'}:
        return ''
    return country

def delegate_org_country_for_row(row: pd.Series | dict[str, Any], *, apply_overrides: bool=True, data_dir: Path | str='data') -> tuple[str, str]:
    """Resolved organisation and country for a delegate row."""
    organisation = organisation_for_delegate_row(row, apply_overrides=apply_overrides)
    country = delegate_country_for_row(row, apply_overrides=apply_overrides)
    if not country:
        country = infer_country_from_organisation(organisation)
    return resolve_compound_org_country(organisation, country, data_dir=data_dir)

def organisation_for_delegate_row(row: pd.Series | dict[str, Any], *, apply_overrides: bool=True) -> str:
    """Resolve the best organisation string for a delegate row."""
    if apply_overrides:
        override = organisation_override_for_row(row)
        if override:
            return override
    return sanitize_delegate_organisation(str(row.get('organisation') or ''), first_name=str(row.get('first_name') or ''), last_name=str(row.get('last_name') or ''), country=str(row.get('country') or ''))

def delegate_affiliation_for_row(row: pd.Series | dict[str, Any], *, apply_overrides: bool=True) -> str:
    """Return a cleaned affiliation string for geocoding and map grouping."""
    from src.registry.affiliation_registry import _make_affiliation
    if isinstance(row, pd.Series):
        row = row.to_dict()
    organisation, country = delegate_org_country_for_row(row, apply_overrides=apply_overrides)
    affiliation = _make_affiliation(organisation, country)
    if affiliation:
        return affiliation
    return str(row.get('affiliation') or '').strip()
_ORGANISATION_COUNTRY_OVERRIDES: dict[str, str] = {'australian institute of marine science': 'Australia', "division of aquatic resources - hawai'i": 'United States', 'division of aquatic resources - hawaii': 'United States', 'global discovery and conservation science': 'United States', 'kaust': 'Saudi Arabia', 'national center for scientific research - rahui center': 'French Polynesia', 'national center for scientific research - rāhui center': 'French Polynesia', 'oregon state university': 'United States', "state of hawai'i": 'United States', 'state of hawaii': 'United States', 'university of auckland': 'New Zealand', 'university of the virgin islands': 'United States Virgin Islands'}

def infer_country_from_organisation(organisation: str) -> str:
    """Infer country when the PDF layout truncates before the country column."""
    org = repair_mojibake(str(organisation or '')).strip()
    if not org:
        return ''
    key = re.sub('\\s+', ' ', org).casefold()
    if key in _ORGANISATION_COUNTRY_OVERRIDES:
        return _ORGANISATION_COUNTRY_OVERRIDES[key]
    if re.search("hawai['\\u2019]?i?\\b", org, re.IGNORECASE):
        return 'United States'
    if re.search('\\baustralian\\b', org, re.IGNORECASE):
        return 'Australia'
    if re.search('\\b(university of auckland|university of waikato|victoria university of wellington)\\b', org, re.IGNORECASE):
        return 'New Zealand'
    return ''

def normalize_delegate_records(delegates: pd.DataFrame, *, apply_overrides: bool=True) -> pd.DataFrame:
    """Repair merged organisation fields from the delegate PDF layout."""
    delegates = delegates.copy()
    for index, row in delegates.iterrows():
        organisation = organisation_for_delegate_row(row, apply_overrides=apply_overrides)
        country = str(row.get('country') or '').strip()
        if apply_overrides:
            country_override = country_override_for_row(row)
            if country_override:
                country = country_override
        if not country:
            country = infer_country_from_organisation(organisation)
        affiliation = delegate_affiliation_for_row({'organisation': organisation, 'country': country, 'affiliation': row.get('affiliation'), 'first_name': row.get('first_name'), 'last_name': row.get('last_name'), 'full_name': row.get('full_name')}, apply_overrides=False)
        delegates.at[index, 'organisation'] = organisation
        delegates.at[index, 'country'] = country
        delegates.at[index, 'affiliation'] = affiliation
        if country:
            delegates.at[index, 'country_code'] = country_to_iso2(country)
    return delegates

def normalize_person_name(value: str) -> str:
    value = TITLE_RE.sub('', str(value).strip().lower())
    value = re.sub('[^a-z0-9\\s]', ' ', value)
    return re.sub('\\s+', ' ', value).strip()

class _UnionFind:

    def __init__(self) -> None:
        self.parent: dict[str, str] = {}

    def find(self, node: str) -> str:
        if node not in self.parent:
            self.parent[node] = node
        parent = self.parent[node]
        if parent != node:
            self.parent[node] = self.find(parent)
        return self.parent[node]

    def union(self, left: str, right: str) -> None:
        root_left = self.find(left)
        root_right = self.find(right)
        if root_left != root_right:
            self.parent[root_right] = root_left
PRESENTER_NODE_SEP = '\x1f'

def normalize_organisation_label(value: str) -> str:
    return normalize_person_name(str(value or '').replace(',', ' '))

def presenter_identity_node(presenter_norm: str, affiliation: str='') -> str:
    aff_norm = normalize_organisation_label(affiliation)
    if aff_norm:
        return f'{presenter_norm}{PRESENTER_NODE_SEP}{aff_norm}'
    return presenter_norm
HONORIFIC_TOKENS = frozenset({'a', 'assoc', 'assistant', 'dr', 'mr', 'mrs', 'ms', 'mx', 'prof', 'sir'})

def _given_name_tokens(name: str) -> list[str]:
    return [token for token in normalize_person_name(name).split() if token and token not in HONORIFIC_TOKENS]

def _person_name_parts(name: str) -> tuple[str, str]:
    tokens = _given_name_tokens(name)
    if not tokens:
        return ('', '')
    if len(tokens) == 1:
        return (tokens[0], tokens[0])
    return (tokens[0], tokens[-1])

def names_likely_same_person(left: str, right: str) -> bool:
    """True when two display names plausibly refer to the same person (nickname-safe)."""
    left_norm = normalize_person_name(left)
    right_norm = normalize_person_name(right)
    if not left_norm or not right_norm:
        return False
    if left_norm == right_norm:
        return True
    left_first, left_last = _person_name_parts(left)
    right_first, right_last = _person_name_parts(right)
    if not left_last or left_last != right_last:
        return False
    if left_first == right_first:
        return True
    return left_first.startswith(right_first) or right_first.startswith(left_first)

def organisations_likely_same(left: str, right: str) -> bool:
    """True when two affiliation labels refer to the same institution."""
    left_norm = normalize_organisation_label(left)
    right_norm = normalize_organisation_label(right)
    if not left_norm or not right_norm:
        return False
    if left_norm == right_norm:
        return True
    return left_norm in right_norm or right_norm in left_norm

def register_talk_presenters(talks: pd.DataFrame, *, presenter_display: dict[str, str], uf: _UnionFind, token_index: dict[str, set[str]]) -> None:
    """Index programme presenters by name tokens and affiliation for homonym disambiguation."""
    for _, talk in talks.iterrows():
        presenter = str(talk.get('presenter') or '').strip()
        if not presenter:
            continue
        affiliation = str(talk.get('affiliation') or '').strip()
        norm = normalize_person_name(presenter)
        node = presenter_identity_node(norm, affiliation)
        presenter_display[node] = presenter
        uf.find(node)
        for token in name_tokens(presenter):
            token_index.setdefault(token, set()).add(node)

def match_delegate_to_presenter_node(delegate_name: str, delegate_organisation: str, token_index: dict[str, set[str]], presenter_display: dict[str, str]) -> str | None:
    """Match a delegate-list name to a programme presenter without merging homonyms."""
    delegate_tokens = name_tokens(delegate_name)
    if not delegate_tokens:
        return None
    tokens = [token for token in delegate_tokens if token in token_index]
    if not tokens:
        tokens = list(delegate_tokens)
    candidates: set[str] | None = None
    for token in tokens:
        matches = token_index.get(token)
        if not matches:
            return None
        candidates = matches if candidates is None else candidates & matches
    if not candidates:
        return None
    filtered: list[str] = []
    for node in candidates:
        presenter_name = presenter_display.get(node, node.split(PRESENTER_NODE_SEP, 1)[0])
        if not names_likely_same_person(delegate_name, presenter_name):
            continue
        presenter_tokens = name_tokens(presenter_name)
        if len(presenter_tokens) > len(delegate_tokens):
            continue
        filtered.append(node)
    if not filtered:
        return None
    if len(filtered) == 1:
        return filtered[0]
    org_norm = normalize_organisation_label(delegate_organisation)
    if org_norm:
        org_matches = [node for node in filtered if PRESENTER_NODE_SEP in node and organisations_likely_same(org_norm, node.split(PRESENTER_NODE_SEP, 1)[1])]
        if len(org_matches) == 1:
            return org_matches[0]
    return None

def delegate_identity_node(name: str, organisation: str='', *, country: str='') -> str:
    """Union-find node for a delegate-list row; affiliation disambiguates homonyms."""
    norm = normalize_person_name(name)
    if not norm:
        return ''
    organisation = str(organisation or '').strip()
    country = str(country or '').strip()
    if organisation:
        from src.registry.affiliation_registry import _make_affiliation
        affiliation = _make_affiliation(organisation, country) if country else organisation
        return presenter_identity_node(norm, affiliation)
    return norm

def link_delegates_to_programme_talks(talks: pd.DataFrame, delegates: pd.DataFrame, *, uf: _UnionFind) -> None:
    """Union delegate-list rows with programme presenters sharing surname + institution."""
    presenters = talks.get('presenter', pd.Series(dtype=str)).fillna('').astype(str)
    affiliations = talks.get('affiliation', pd.Series(dtype=str)).fillna('').astype(str)
    by_org: dict[str, list[tuple[str, str]]] = {}
    seen_pairs: set[tuple[str, str]] = set()
    for presenter, affiliation in zip(presenters, affiliations, strict=False):
        presenter = presenter.strip()
        affiliation = affiliation.strip()
        if not presenter or not affiliation:
            continue
        pair_key = (presenter.casefold(), affiliation.casefold())
        if pair_key in seen_pairs:
            continue
        seen_pairs.add(pair_key)
        org_norm = normalize_organisation_label(affiliation)
        if not org_norm:
            continue
        node = presenter_identity_node(normalize_person_name(presenter), affiliation)
        by_org.setdefault(org_norm, []).append((presenter, node))
    if not by_org:
        return
    org_norms = list(by_org.keys())
    for _, row in delegates.iterrows():
        delegate_name = str(row.get('full_name') or '').strip()
        if not delegate_name:
            continue
        organisation, country = delegate_org_country_for_row(row)
        delegate_org_norm = normalize_organisation_label(organisation)
        if not delegate_org_norm:
            continue
        delegate_node = delegate_identity_node(delegate_name, organisation, country=country)
        uf.find(delegate_node)
        if delegate_org_norm in by_org:
            candidate_orgs = [delegate_org_norm]
        else:
            candidate_orgs = [org_norm for org_norm in org_norms if organisations_likely_same(delegate_org_norm, org_norm)]
        for org_norm in candidate_orgs:
            for presenter, node in by_org[org_norm]:
                if not names_likely_same_person(delegate_name, presenter):
                    continue
                uf.find(node)
                uf.union(delegate_node, node)

def _match_single_presenter_norm(name: str, token_index: dict[str, set[str]]) -> str | None:
    tokens = name_tokens(name)
    if not tokens:
        return None
    candidate_norms: set[str] | None = None
    for token in tokens:
        matches = token_index.get(token)
        if not matches:
            return None
        candidate_norms = matches if candidate_norms is None else candidate_norms & matches
    if candidate_norms and len(candidate_norms) == 1:
        return next(iter(candidate_norms))
    return None

def delegate_person_key(name: str, *, affiliation: str='') -> str:
    """Return a stable icrs-p-* person key from the registry."""
    from src.registry.key_resolution import resolve_person_key
    cleaned = str(name or '').strip()
    if not cleaned:
        return ''
    person_key = resolve_person_key(cleaned, affiliation=affiliation)
    return person_key if person_key.startswith('icrs-p-') else ''

def canonical_person_name(name: str) -> str:
    """Return the preferred display name for a person across talk/delegate aliases."""
    from src.registry.key_resolution import get_registry_key_resolver, resolve_person_key
    cleaned = str(name or '').strip()
    if not cleaned:
        return ''
    person_key = resolve_person_key(cleaned)
    if person_key:
        canonical = get_registry_key_resolver().canonical_name(person_key, fallback=cleaned)
        if canonical:
            return canonical
    return cleaned

def name_tokens(value: str) -> set[str]:
    return {token for token in normalize_person_name(value).split() if len(token) > 1}

def repair_mojibake(text: str) -> str:
    """Repair UTF-8 text that was mis-decoded as MacRoman (√≥ → ó, etc.)."""
    value = str(text or '')
    if not value or not _MOJIBAKE_MARKERS_RE.search(value):
        return value
    try:
        repaired = value.encode('mac_roman').decode('utf-8')
    except UnicodeError:
        return value
    if repaired.count('�') >= value.count('�'):
        return repaired
    return value

def country_to_iso2(country_name: str) -> str:
    cleaned = repair_mojibake(str(country_name)).strip()
    if not cleaned:
        return ''
    alias = COUNTRY_ALIASES.get(cleaned.casefold())
    lookup_name = alias or cleaned
    pycountry_names = {'South Korea': 'Korea, Republic of', 'United States Virgin Islands': 'Virgin Islands, U.S.', 'Sint Maarten': 'Sint Maarten (Dutch part)', 'Curaçao': 'Curaçao'}
    lookup_name = pycountry_names.get(lookup_name, lookup_name)
    try:
        return pycountry.countries.lookup(lookup_name).alpha_2
    except LookupError:
        direct = {'south korea': 'KR', 'korea, republic of': 'KR', 'sint maarten': 'SX', 'united states virgin islands': 'VI', 'virgin islands (u.s.)': 'VI', 'northern mariana islands': 'MP', 'micronesia, federated states of': 'FM', 'curaçao': 'CW', 'curacao': 'CW'}
        return direct.get(cleaned.casefold(), '')

def extract_layout_text(pdf_path: Path=DEFAULT_DELEGATE_PDF_PATH, *, cache_path: Path=DEFAULT_DELEGATES_LAYOUT_CACHE, refresh: bool=False) -> str:
    pdf_path = Path(pdf_path)
    cache_path = Path(cache_path)
    if not refresh and cache_path.exists() and (cache_path.stat().st_mtime >= pdf_path.stat().st_mtime):
        return repair_mojibake(cache_path.read_text(encoding='utf-8'))
    result = subprocess.run(['pdftotext', '-enc', 'UTF-8', '-layout', str(pdf_path), '-'], check=True, capture_output=True)
    text = repair_mojibake(result.stdout.decode('utf-8'))
    cache_path.write_text(text, encoding='utf-8')
    return text

def _known_country_suffixes() -> list[str]:
    global _COUNTRY_SUFFIXES
    if _COUNTRY_SUFFIXES is not None:
        return _COUNTRY_SUFFIXES
    names = set(_EXTRA_COUNTRY_NAMES)
    names.update((country.name for country in pycountry.countries))
    names.update(COUNTRY_ALIASES.keys())
    names.update(COUNTRY_ALIASES.values())
    names.update((' '.join((part.capitalize() for part in key.split())) for key in COUNTRY_ALIASES))
    _COUNTRY_SUFFIXES = sorted(names, key=len, reverse=True)
    return _COUNTRY_SUFFIXES

def _canonicalize_country(name: str) -> str:
    cleaned = repair_mojibake(name).strip()
    if not cleaned:
        return ''
    alias = COUNTRY_ALIASES.get(cleaned.casefold())
    if alias:
        return alias
    for known in _known_country_suffixes():
        if known.casefold() == cleaned.casefold():
            return known
    return cleaned

def _match_country_label(text: str) -> tuple[str | None, bool]:
    """Return (country_label, needs_wrap_continuation)."""
    cleaned = repair_mojibake(text).strip().rstrip(',')
    if not cleaned or len(cleaned) < 2:
        return (None, False)
    if country_to_iso2(cleaned):
        return (_canonicalize_country(cleaned), False)
    fold = cleaned.casefold()
    prefix_hits = [name for name in _known_country_suffixes() if name.casefold().startswith(fold) and len(cleaned) >= 6]
    prefix_hits = sorted(set(prefix_hits), key=lambda item: (len(item), item))
    if len(prefix_hits) == 1:
        label = _canonicalize_country(prefix_hits[0])
        return (label, label.casefold() != fold and (not fold.endswith(label.casefold().split()[-1])))
    if len(prefix_hits) > 1:
        canon = {_canonicalize_country(item) for item in prefix_hits}
        if len(canon) == 1:
            label = next(iter(canon))
            return (label, True)
        label = _canonicalize_country(prefix_hits[0])
        return (label, True)
    if fold.startswith('micronesia'):
        return ('Micronesia, Federated States of', True)
    if fold.startswith('northern mariana'):
        return ('Northern Mariana Islands', True)
    if fold.startswith('venezuela'):
        return ('Venezuela, Bolivarian Republic of', True)
    if fold.startswith('tanzania'):
        return ('Tanzania, United Republic of', True)
    if fold.startswith('bolivia'):
        return ('Bolivia, Plurinational State of', True)
    return (None, False)

def _country_is_incomplete(label: str) -> bool:
    cleaned = repair_mojibake(label).strip()
    if not cleaned:
        return False
    fold = cleaned.casefold()
    if fold in {'northern mariana', 'micronesia (the', 'venezuela, bolivarian', 'tanzania, united', 'bolivia, plurinational'}:
        return True
    matched, incomplete = _match_country_label(cleaned)
    if matched and incomplete:
        return True
    if matched and country_to_iso2(matched):
        return False
    return cleaned.endswith((',', '(')) or fold.endswith('(the')

def _merge_wrapped_country(existing: str, addition: str) -> str:
    existing = repair_mojibake(existing).strip()
    addition = repair_mojibake(addition).strip()
    if not addition:
        return existing
    if not existing:
        matched, _ = _match_country_label(addition)
        return matched or addition
    candidates = [f'{existing} {addition}', f'{existing}{addition}', re.sub('\\s+', ' ', f'{existing} {addition}').strip()]
    candidates.append(re.sub('\\s+', ' ', f'{existing} {addition}').replace(' )', ')').strip())
    for candidate in candidates:
        matched, incomplete = _match_country_label(candidate)
        if matched and (not incomplete) and country_to_iso2(matched):
            return matched
        if country_to_iso2(candidate):
            return _canonicalize_country(candidate)
    matched, _ = _match_country_label(f'{existing} {addition}'.strip())
    return matched or f'{existing} {addition}'.strip()

def _layout_fields(line: str) -> list[tuple[int, str]]:
    """Split a layout line into columns; only single spaces allowed within a field."""
    return [(match.start(), match.group()) for match in re.finditer('\\S+(?: \\S+)*(?=\\s{2,}|\\s*$)', line)]

def _is_skippable_layout_line(line: str) -> bool:
    if not line.startswith('    ') or not line.strip():
        return True
    markers = ('First name', 'List of Delegates', 'Excluding those', 'Created ')
    if any((marker in line for marker in markers)):
        return True
    return line.strip().startswith('Page:')

def _parse_person_layout_line(line: str) -> dict[str, Any]:
    stripped = repair_mojibake(line).rstrip()
    fields = _layout_fields(stripped)
    first = stripped[COL_FIRST:COL_LAST].strip() if len(stripped) > COL_FIRST else ''
    if fields and fields[0][0] < COL_LAST:
        rest = fields[1:]
    else:
        rest = fields
    last = ''
    remainder = rest
    if rest and rest[0][0] < _ORG_COL_MIN:
        last = rest[0][1]
        remainder = rest[1:]
    organisation = ''
    country = ''
    country_incomplete = False
    if remainder:
        country_text = remainder[-1][1]
        matched, incomplete = _match_country_label(country_text)
        if matched:
            country = country_text if incomplete else matched
            country_incomplete = incomplete or _country_is_incomplete(country_text)
            organisation = ' '.join((text for _, text in remainder[:-1])).strip()
        else:
            organisation = ' '.join((text for _, text in remainder)).strip()
    organisation = re.sub('\\s+', ' ', organisation).strip()
    return {'first_name': first, 'last_name': last, 'organisation': organisation, 'country': country, '_country_incomplete': country_incomplete, '_org_incomplete': is_incomplete_organisation(organisation)}

def _append_continuation(current: dict[str, Any], line: str) -> None:
    stripped = repair_mojibake(line).rstrip()
    fields = _layout_fields(stripped)
    if not fields:
        return
    org_bits: list[str] = []
    country_bits: list[str] = []
    for start, text in fields:
        if start >= _COUNTRY_COL_MIN:
            country_bits.append(text)
        else:
            org_bits.append(text)
    if country_bits:
        addition = ' '.join(country_bits)
        current['country'] = _merge_wrapped_country(str(current.get('country') or ''), addition)
        current['_country_incomplete'] = _country_is_incomplete(str(current.get('country') or ''))
    if org_bits:
        addition = ' '.join(org_bits)
        merged = f"{current.get('organisation', '')} {addition}".strip()
        current['organisation'] = re.sub('\\s+', ' ', merged)
        current['_org_incomplete'] = is_incomplete_organisation(current['organisation'])

def parse_delegate_layout_text(text: str) -> pd.DataFrame:
    """Parse pdftotext -layout output into delegate records."""
    records: list[dict[str, str]] = []
    current: dict[str, Any] | None = None
    ignore_continuations = False

    def flush() -> None:
        nonlocal current
        if current is None:
            return
        record = {'first_name': str(current.get('first_name') or '').strip(), 'last_name': str(current.get('last_name') or '').strip(), 'organisation': re.sub('\\s+', ' ', str(current.get('organisation') or '')).strip(), 'country': _canonicalize_country(str(current.get('country') or ''))}
        records.append(record)
        current = None
    for raw_line in repair_mojibake(text).splitlines():
        line = raw_line.rstrip('\n')
        if _is_skippable_layout_line(line):
            if any((marker in line for marker in ('First name', 'List of Delegates', 'Page:'))):
                ignore_continuations = True
            continue
        first = line[COL_FIRST:COL_LAST].strip() if len(line) > COL_FIRST else ''
        if first:
            flush()
            ignore_continuations = False
            current = _parse_person_layout_line(line)
            continue
        if current is None or ignore_continuations:
            continue
        fields = _layout_fields(line)
        has_country_col = any((start >= _COUNTRY_COL_MIN for start, _ in fields))
        if current.get('_org_incomplete') or current.get('_country_incomplete') or has_country_col:
            _append_continuation(current, line)
    flush()
    if not records:
        return pd.DataFrame(columns=['first_name', 'last_name', 'organisation', 'country', 'full_name', 'affiliation'])
    df = pd.DataFrame(records)
    df['full_name'] = (df['first_name'].str.strip() + ' ' + df['last_name'].str.strip()).str.strip()
    df = normalize_delegate_records(df, apply_overrides=False)
    df['country_code'] = df['country'].map(country_to_iso2)
    return df

def load_delegates(*, pdf_path: Path=DEFAULT_DELEGATE_PDF_PATH, json_path: Path=DEFAULT_DELEGATES_JSON_PATH, refresh: bool=False) -> pd.DataFrame:
    pdf_path = Path(pdf_path)
    json_path = Path(json_path)
    if json_path.exists() and (not refresh) and (not pdf_path.exists() or json_path.stat().st_mtime >= pdf_path.stat().st_mtime):
        payload = load_json(json_path)
        return normalize_delegate_records(pd.DataFrame(payload['delegates']), apply_overrides=False)
    if not pdf_path.exists():
        if json_path.exists():
            payload = load_json(json_path)
            return normalize_delegate_records(pd.DataFrame(payload['delegates']), apply_overrides=False)
        raise FileNotFoundError(f'Delegate PDF not found: {pdf_path}. Place the list PDF there or keep {json_path} up to date.')
    text = extract_layout_text(pdf_path, refresh=refresh)
    delegates = parse_delegate_layout_text(text)
    delegates = mark_delegate_speakers(delegates)
    save_delegates(delegates, json_path=json_path, source_pdf=pdf_path)
    return delegates

def mark_delegate_speakers(delegates: pd.DataFrame) -> pd.DataFrame:
    talks = load_talks()
    presenters = talks[['presenter']].dropna().drop_duplicates().assign(norm=lambda frame: frame['presenter'].map(normalize_person_name))
    presenter_norms = set(presenters['norm'])
    presenter_tokens = presenters['norm'].map(name_tokens).tolist()
    delegates = delegates.copy()
    delegates['norm_name'] = delegates['full_name'].map(normalize_person_name)
    delegates['is_speaker'] = delegates['norm_name'].isin(presenter_norms)
    token_index: dict[str, set[str]] = {}
    for norm, tokens in zip(presenters['norm'], presenter_tokens, strict=False):
        for token in tokens:
            token_index.setdefault(token, set()).add(norm)
    for index, row in delegates.loc[~delegates['is_speaker']].iterrows():
        tokens = name_tokens(row['full_name'])
        if not tokens:
            continue
        candidate_norms: set[str] | None = None
        for token in tokens:
            matches = token_index.get(token)
            if not matches:
                candidate_norms = None
                break
            candidate_norms = matches if candidate_norms is None else candidate_norms & matches
        if candidate_norms and len(candidate_norms) == 1:
            delegates.at[index, 'is_speaker'] = True
    return _apply_registry_speaker_flags(delegates)

def _truthy_speaker_flag(value: object) -> bool:
    return str(value or '').strip().lower() in {'true', '1', 'yes'}

def _apply_registry_speaker_flags(delegates: pd.DataFrame) -> pd.DataFrame:
    """Mark delegates as speakers when the person registry links them to programme presenters."""
    from src.data_paths import PERSON_REGISTRY_CSV
    if not Path(PERSON_REGISTRY_CSV).exists():
        return delegates
    from src.registry.key_resolution import get_registry_key_resolver
    resolver = get_registry_key_resolver()
    delegates = delegates.copy()
    for index, row in delegates.loc[~delegates['is_speaker']].iterrows():
        name = str(row.get('full_name') or '').strip()
        if not name:
            continue
        organisation, country = delegate_org_country_for_row(row)
        from src.registry.affiliation_registry import _make_affiliation
        affiliation = _make_affiliation(organisation, country) if organisation else organisation
        person_key = resolver.resolve_person_key(name, affiliation=affiliation)
        if not person_key:
            continue
        person = resolver.people_by_key.get(person_key)
        if person is not None and _truthy_speaker_flag(person.get('is_speaker')):
            delegates.at[index, 'is_speaker'] = True
    return delegates

def _delegate_is_speaker(name: str, affiliation: str, *, delegate_flag: bool, person_key: str='', resolver: Any | None=None) -> bool:
    if delegate_flag:
        return True
    if not resolver:
        return False
    key = person_key or resolver.resolve_person_key(name, affiliation=affiliation)
    if not key:
        return False
    person = resolver.people_by_key.get(key)
    return person is not None and _truthy_speaker_flag(person.get('is_speaker'))

def delegate_list_groups(delegates: pd.DataFrame | None=None, *, show_progress: bool=False) -> list[dict[str, Any]]:
    """Group all delegate-list attendees by affiliation for the map site."""
    from src.geocoding.geocode import affiliation_display_name, canonical_affiliation_key
    from src.registry.key_resolution import get_registry_key_resolver, resolve_affiliation_key
    from src.site.export_progress import iterrows_with_progress
    from src.site.map_exclusions import is_map_excluded, load_map_exclusions
    if delegates is None:
        delegates = load_delegates()
    map_exclusions = load_map_exclusions()
    resolver = get_registry_key_resolver()
    groups: dict[str, dict[str, Any]] = {}
    for _, row in iterrows_with_progress(delegates, 'Grouping delegates by affiliation', show_progress=show_progress):
        affiliation = delegate_affiliation_for_row(row)
        if not affiliation:
            continue
        name = str(row.get('full_name') or '').strip()
        if not name or is_map_excluded(name, set(map_exclusions.names)):
            continue
        display = affiliation_display_name(affiliation) or organisation_for_delegate_row(row)
        if is_incomplete_organisation(display):
            continue
        organisation, country = delegate_org_country_for_row(row)
        registry_aff_key = resolve_affiliation_key(organisation, country)
        key = registry_aff_key or canonical_affiliation_key(affiliation).casefold()
        group = groups.setdefault(key, {'affiliation_key': key, 'affiliation': display, 'delegates': []})
        if len(display) > len(group['affiliation']):
            group['affiliation'] = display
        country = delegate_country_for_row(row)
        person_key = str(row.get('person_key') or '').strip()
        if not person_key:
            person_key = resolver.resolve_person_key(name, affiliation=affiliation)
        is_speaker = _delegate_is_speaker(
            name,
            affiliation,
            delegate_flag=bool(row.get('is_speaker')),
            person_key=person_key,
            resolver=resolver,
        )
        group['delegates'].append({'name': name, 'search_text': ' '.join((part for part in (name, display, country) if part)).lower(), 'is_speaker': is_speaker, 'person_key': person_key})
    for group in groups.values():
        group['delegates'].sort(key=lambda item: item['name'].casefold())
    return sorted(groups.values(), key=lambda item: item['affiliation'].casefold())

def export_non_speaking_delegates_js(save_path: str | Path='js/non-speaking-delegates.js', *, delegates: pd.DataFrame | None=None, show_progress: bool=False) -> Path:
    """Export delegate-list groups and name→person_key aliases for the map site."""
    from src.registry.key_resolution import get_registry_key_resolver
    resolver = get_registry_key_resolver()
    groups = delegate_list_groups(delegates, show_progress=show_progress)
    output_path = Path(save_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    body = f'/** Generated from data/sources/delegates.json – do not edit by hand. */\nexport const NON_SPEAKING_DELEGATE_GROUPS = {json.dumps(groups, ensure_ascii=False, indent=2)};\nexport const DELEGATE_PERSON_KEY_ALIASES = {json.dumps(resolver.variant_to_key, ensure_ascii=False, indent=2)};\nexport const PERSON_CANONICAL_NAMES = {json.dumps(resolver.key_to_canonical, ensure_ascii=False, indent=2)};\n'
    output_path.write_text(body, encoding='utf-8')
    return output_path

def save_delegates(delegates: pd.DataFrame, *, json_path: Path=DEFAULT_DELEGATES_JSON_PATH, source_pdf: Path=DEFAULT_DELEGATE_PDF_PATH) -> Path:
    payload = {'meta': {'source_pdf': str(source_pdf), 'delegate_count': len(delegates), 'speaker_count': int(delegates['is_speaker'].sum()), 'non_speaker_count': int((~delegates['is_speaker']).sum())}, 'delegates': delegates.to_dict(orient='records')}
    save_json(Path(json_path), payload, sort_keys=False, ensure_ascii=True)
    return Path(json_path)
