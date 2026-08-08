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
from src.data_paths import (
    DELEGATE_ORG_OVERRIDES_CSV,
    DELEGATE_PDF,
    DELEGATES_JSON,
    DELEGATES_LAYOUT_TXT,
    delegate_id_match_review_files,
)

DEFAULT_DELEGATE_PDF_PATH = DELEGATE_PDF
DEFAULT_DELEGATES_JSON_PATH = DELEGATES_JSON
DEFAULT_DELEGATES_LAYOUT_CACHE = DELEGATES_LAYOUT_TXT
DEFAULT_ORG_OVERRIDES_PATH = DELEGATE_ORG_OVERRIDES_CSV
DEFAULT_ORG_REVIEW_PATH = DELEGATE_ORG_OVERRIDES_CSV.parent / "delegate_organisation_review.csv"
DEFAULT_ID_MATCH_REVIEW_GLOB = "delegate_id_match_review_*_merged.csv"

_ORGANISATION_OVERRIDE_CACHE: dict[str, tuple[str, str]] | None = None
_DELEGATE_PERSON_KEY_CACHE: dict[str, str] | None = None
_PERSON_IDENTITY_CACHE: tuple[dict[str, str], dict[str, str]] | None = None

COL_FIRST = 4
COL_LAST = 32
COL_ORG = 57
COL_COUNTRY = 114
# Layout country text usually begins near here; used for wrap-line routing.
_COUNTRY_COL_MIN = 90
# Last-name column starts at COL_LAST; organisation text is further right.
_ORG_COL_MIN = 45

TITLE_RE = re.compile(r"^(dr|prof|professor|mr|mrs|ms|miss)\.?\s+", re.IGNORECASE)
_MOJIBAKE_MARKERS_RE = re.compile(r"[√ÃÂ]")

COUNTRY_ALIASES = {
    "united states": "United States",
    "united kingdom": "United Kingdom",
    "hong kong": "Hong Kong",
    "french polynesia": "French Polynesia",
    "marshall islands": "Marshall Islands",
    "south korea": "South Korea",
    "korea, republic of": "South Korea",
    "republic of korea": "South Korea",
    "taiwan": "Taiwan",
    "russia": "Russian Federation",
    "vietnam": "Viet Nam",
    "bolivia": "Bolivia, Plurinational State of",
    "bolivia, plurinational state of": "Bolivia, Plurinational State of",
    "iran": "Iran, Islamic Republic of",
    "tanzania": "Tanzania, United Republic of",
    "tanzania, united republic of": "Tanzania, United Republic of",
    "venezuela": "Venezuela, Bolivarian Republic of",
    "venezuela, bolivarian republic of": "Venezuela, Bolivarian Republic of",
    "usa": "United States",
    "uk": "United Kingdom",
    "uae": "United Arab Emirates",
    "papua new guinea": "Papua New Guinea",
    "new zealand": "New Zealand",
    "saudi arabia": "Saudi Arabia",
    "south africa": "South Africa",
    "cook islands": "Cook Islands",
    "solomon islands": "Solomon Islands",
    "northern mariana islands": "Northern Mariana Islands",
    "northern mariana": "Northern Mariana Islands",
    "federated states of micronesia": "Micronesia, Federated States of",
    "micronesia": "Micronesia, Federated States of",
    "micronesia (the federated states of)": "Micronesia, Federated States of",
    "micronesia (the": "Micronesia, Federated States of",
    "virgin islands (u.s.)": "United States Virgin Islands",
    "virgin islands (us)": "United States Virgin Islands",
    "u.s. virgin islands": "United States Virgin Islands",
    "us virgin islands": "United States Virgin Islands",
    "united states virgin islands": "United States Virgin Islands",
    "sint maarten": "Sint Maarten",
    "nederland": "Netherlands",
    "netherlands": "Netherlands",
    "curaçao": "Curaçao",
    "curacao": "Curaçao",
}

_EXTRA_COUNTRY_NAMES = {
    "Hong Kong",
    "Taiwan",
    "New Zealand",
    "United States",
    "United Kingdom",
    "United Arab Emirates",
    "Papua New Guinea",
    "French Polynesia",
    "Saudi Arabia",
    "South Africa",
    "Cook Islands",
    "Solomon Islands",
    "Northern Mariana Islands",
    "Micronesia, Federated States of",
    "Federated States of Micronesia",
    "South Korea",
    "Korea, Republic of",
    "Sint Maarten",
    "United States Virgin Islands",
    "Virgin Islands (U.S.)",
    "American Samoa",
    "Puerto Rico",
    "Palau",
    "Maldives",
    "Mauritius",
    "Seychelles",
    "Vanuatu",
    "Samoa",
    "Fiji",
    "Indonesia",
    "Philippines",
    "Australia",
    "Japan",
    "China",
    "India",
    "Brazil",
    "Egypt",
    "Israel",
    "Germany",
    "France",
    "Canada",
    "Mexico",
    "Jamaica",
    "Kenya",
    "Madagascar",
    "Malaysia",
    "Singapore",
    "Thailand",
    "Viet Nam",
    "Spain",
    "Italy",
    "Netherlands",
    "Belgium",
    "Switzerland",
    "Sweden",
    "Norway",
    "Denmark",
    "Finland",
    "Ireland",
    "Portugal",
    "Greece",
    "Poland",
    "Austria",
    "Czechia",
    "Hungary",
    "Romania",
    "Turkey",
    "Qatar",
    "Kuwait",
    "Oman",
    "Bahrain",
    "Jordan",
    "Lebanon",
    "Morocco",
    "Tunisia",
    "Nigeria",
    "Ghana",
    "Tanzania, United Republic of",
    "South Sudan",
    "Ethiopia",
    "Mozambique",
    "Zimbabwe",
    "Botswana",
    "Namibia",
    "Zambia",
    "Uganda",
    "Rwanda",
    "Cameroon",
    "Senegal",
    "Colombia",
    "Ecuador",
    "Peru",
    "Chile",
    "Argentina",
    "Uruguay",
    "Panama",
    "Costa Rica",
    "Honduras",
    "Guatemala",
    "Cuba",
    "Dominican Republic",
    "Trinidad and Tobago",
    "Barbados",
    "Bahamas",
    "Belize",
    "Guam",
    "Hawaii, USA",
    "Pohnpei, Federated States of Micronesia",
}

_COUNTRY_SUFFIXES: list[str] | None = None

_ORG_HINT_RE = re.compile(
    r"\b(?:university|institute|college|school|department|division|dept|center|centre|"
    r"laboratory|laboratories|research|national|marine|sciences?|conservancy|foundation|"
    r"ministry|agency|government|state of|cooperative|museum|corporation|corp|"
    r"organization|organisation|limited|ltd|inc|consulting|studies|resources?|"
    r"management|bureau|office|authority|commission|programme|program|unit|fund|"
    r"academy|society|association|network|partners|group|company|tech|a&m)\b",
    re.IGNORECASE,
)

_BLEED_NAME_RE = re.compile(r"^[A-Z][a-z'`-]+(?:\s+[A-Z][a-z'`-]+){0,2}$")

_TITLE_TOKENS = frozenset({"dr", "prof", "professor", "mr", "mrs", "ms", "miss"})

_BLEED_TITLE_NAME_RE = re.compile(
    r"^(.*?)(?:\s+(?:Dr|Prof|Professor|Mr|Mrs|Ms|Miss)\.?\s+[A-Z].*)$",
    re.IGNORECASE,
)

_INCOMPLETE_ORG_ENDINGS = frozenset(
    {"of", "the", "and", "for", "at", "in", "de", "du", "la", "le", "-", "&"}
)


def is_incomplete_organisation(name: str) -> bool:
    cleaned = str(name or "").strip()
    if not cleaned:
        return True
    if cleaned.casefold() in {"nan", "national", "lumpkin"}:
        return True
    if re.search(r"\s/\s*$", cleaned):
        return True
    if cleaned in ("University of", "University of the"):
        return True
    last = cleaned.split()[-1].casefold().rstrip(".")
    if last in _INCOMPLETE_ORG_ENDINGS:
        return True
    # Directional/region words alone after "University of" usually mean truncation.
    parts = [part for part in cleaned.split() if part]
    return (
        len(parts) == 3
        and parts[0].casefold() == "university"
        and parts[1].casefold() == "of"
        and parts[2].casefold()
        in {
            "southern",
            "northern",
            "eastern",
            "western",
            "central",
            "virgin",
            "new",
            "south",
            "north",
            "east",
            "west",
        }
    )


def _is_title_token(word: str) -> bool:
    return word.casefold().rstrip(".") in _TITLE_TOKENS


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
    return " ".join(words).strip()


def _segment_is_bleed_person_name(segment: str) -> bool:
    segment = segment.strip()
    if not segment or _ORG_HINT_RE.search(segment):
        return False
    words = segment.split()
    if len(words) > 3:
        return False
    if _BLEED_NAME_RE.match(segment):
        return True
    return len(words) == 1 and words[0][0].isupper() and len(words[0]) > 2


def _strip_trailing_bleed_name(
    segment: str,
    first_name: str,
    last_name: str,
    *,
    aggressive: bool = False,
) -> str:
    """Remove glued-on ``Dr Firstname …`` suffixes from a merged PDF column."""
    del aggressive  # kept for call-site compatibility
    del first_name, last_name
    original = re.sub(r"\s+", " ", segment).strip()
    segment = _split_bleed_title_name(original)
    return _strip_trailing_title_only(segment)


def sanitize_delegate_organisation(
    organisation: str,
    *,
    first_name: str = "",
    last_name: str = "",
    country: str = "",
) -> str:
    """Extract the primary organisation when PDF columns bleed into each other."""
    raw = str(organisation or "").strip()
    if not raw:
        return ""

    if not re.search(r"\s{2,}", raw):
        single = re.sub(r"\s+", " ", raw)
        result = _strip_trailing_bleed_name(single, first_name, last_name)
        if is_incomplete_organisation(result):
            return single
        return result

    segments = [part.strip() for part in re.split(r"\s{2,}", raw) if part.strip()]
    country_fold = country.strip().casefold()
    cleaned: list[str] = []
    for segment in segments:
        if _segment_is_bleed_person_name(segment):
            continue
        if country_fold and segment.casefold() == country_fold:
            continue
        if country and segment in _known_country_suffixes():
            continue
        cleaned.append(
            _strip_trailing_bleed_name(
                segment,
                first_name,
                last_name,
                aggressive=bool(_BLEED_TITLE_NAME_RE.search(segment)),
            )
        )

    org_like = [segment for segment in cleaned if _ORG_HINT_RE.search(segment)]
    pick = (org_like or cleaned or [raw])[0]
    result = _strip_trailing_bleed_name(
        re.sub(r"\s+", " ", pick).strip(),
        first_name,
        last_name,
        aggressive=bool(_BLEED_TITLE_NAME_RE.search(pick)),
    )
    if is_incomplete_organisation(result):
        fallback = re.sub(r"\s+", " ", raw).strip()
        fallback = _strip_trailing_title_only(_split_bleed_title_name(fallback))
        if fallback and not is_incomplete_organisation(fallback):
            return fallback
    return result


def load_organisation_overrides(
    path: Path = DEFAULT_ORG_OVERRIDES_PATH,
) -> dict[str, tuple[str, str]]:
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
        organisation = str(row.get("organisation") or "").strip()
        if not organisation:
            continue
        country_raw = row.get("country")
        if pd.isna(country_raw):
            country = ""
        else:
            country = str(country_raw).strip()
        if country.casefold() in {"", "nan", "none"}:
            country = ""
        for name_column in ("full_name", "name"):
            name = str(row.get(name_column) or "").strip()
            if not name:
                continue
            overrides[normalize_person_name(name)] = (organisation, country)
            overrides[name.casefold()] = (organisation, country)

    if path == DEFAULT_ORG_OVERRIDES_PATH:
        _ORGANISATION_OVERRIDE_CACHE = overrides
    return overrides


def delegate_override_for_row(
    row: pd.Series | dict[str, Any],
) -> tuple[str, str] | None:
    if isinstance(row, pd.Series):
        row = row.to_dict()
    overrides = load_organisation_overrides()
    for key in (
        normalize_person_name(str(row.get("full_name") or "")),
        str(row.get("full_name") or "").strip().casefold(),
        normalize_person_name(str(row.get("presenter") or "")),
        str(row.get("presenter") or "").strip().casefold(),
    ):
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
    country = str(override[1] or "").strip()
    if country.casefold() in {"", "nan", "none"}:
        return None
    return country


def resolve_compound_org_country(
    organisation: str,
    country: str,
    *,
    data_dir: Path | str = "data",
) -> tuple[str, str]:
    """Map compound affiliations to reviewed primary org + country."""
    organisation = str(organisation or "").strip()
    country = str(country or "").strip()
    if country.casefold() in {"", "nan", "none"}:
        country = ""
    if not organisation:
        return organisation, country
    from src.registry.affiliation_registry import (
        _build_org_redirects,
        _resolve_attendee_org_country,
        load_affiliation_review,
    )

    reviews = load_affiliation_review(data_dir)
    if reviews.empty:
        return organisation, country
    return _resolve_attendee_org_country(
        organisation,
        country,
        _build_org_redirects(reviews),
    )


def resolve_compound_affiliation_string(affiliation: str, *, data_dir: Path | str = "data") -> str:
    """Return affiliation text with compound orgs mapped to reviewed primary."""
    from src.registry.affiliation_registry import parse_affiliation_parts

    organisation, country = parse_affiliation_parts(str(affiliation or ""))
    organisation, country = resolve_compound_org_country(
        organisation, country, data_dir=data_dir
    )
    if organisation and country:
        return f"{organisation}, {country}"
    return organisation or str(affiliation or "").strip()


def delegate_country_for_row(
    row: pd.Series | dict[str, Any],
    *,
    apply_overrides: bool = True,
) -> str:
    if isinstance(row, pd.Series):
        row = row.to_dict()
    if apply_overrides:
        override = country_override_for_row(row)
        if override:
            return override
    raw_country = row.get("country")
    if pd.isna(raw_country):
        return ""
    country = str(raw_country or "").strip()
    if country.casefold() in {"", "nan", "none"}:
        return ""
    return country


def delegate_org_country_for_row(
    row: pd.Series | dict[str, Any],
    *,
    apply_overrides: bool = True,
    data_dir: Path | str = "data",
) -> tuple[str, str]:
    """Resolved organisation and country for a delegate row."""
    organisation = organisation_for_delegate_row(row, apply_overrides=apply_overrides)
    country = delegate_country_for_row(row, apply_overrides=apply_overrides)
    if not country:
        country = infer_country_from_organisation(organisation)
    return resolve_compound_org_country(organisation, country, data_dir=data_dir)


def organisation_for_delegate_row(
    row: pd.Series | dict[str, Any],
    *,
    apply_overrides: bool = True,
) -> str:
    """Resolve the best organisation string for a delegate row."""
    if apply_overrides:
        override = organisation_override_for_row(row)
        if override:
            return override
    return sanitize_delegate_organisation(
        str(row.get("organisation") or ""),
        first_name=str(row.get("first_name") or ""),
        last_name=str(row.get("last_name") or ""),
        country=str(row.get("country") or ""),
    )


def delegate_affiliation_for_row(
    row: pd.Series | dict[str, Any],
    *,
    apply_overrides: bool = True,
) -> str:
    """Return a cleaned affiliation string for geocoding and map grouping."""
    if isinstance(row, pd.Series):
        row = row.to_dict()
    organisation, country = delegate_org_country_for_row(
        row, apply_overrides=apply_overrides
    )
    if organisation and country:
        return f"{organisation}, {country}"
    return organisation or str(row.get("affiliation") or "").strip()


# PDF rows with long organisation names often omit the country column entirely.
_ORGANISATION_COUNTRY_OVERRIDES: dict[str, str] = {
    "australian institute of marine science": "Australia",
    "division of aquatic resources - hawai'i": "United States",
    "division of aquatic resources - hawaii": "United States",
    "global discovery and conservation science": "United States",
    "kaust": "Saudi Arabia",
    "national center for scientific research - rahui center": "French Polynesia",
    "national center for scientific research - rāhui center": "French Polynesia",
    "oregon state university": "United States",
    "state of hawai'i": "United States",
    "state of hawaii": "United States",
    "university of auckland": "New Zealand",
    "university of the virgin islands": "United States Virgin Islands",
}


def infer_country_from_organisation(organisation: str) -> str:
    """Infer country when the PDF layout truncates before the country column."""
    org = repair_mojibake(str(organisation or "")).strip()
    if not org:
        return ""

    key = re.sub(r"\s+", " ", org).casefold()
    if key in _ORGANISATION_COUNTRY_OVERRIDES:
        return _ORGANISATION_COUNTRY_OVERRIDES[key]

    if re.search(r"hawai['\u2019]?i?\b", org, re.IGNORECASE):
        return "United States"
    if re.search(r"\baustralian\b", org, re.IGNORECASE):
        return "Australia"
    if re.search(
        r"\b(university of auckland|university of waikato|victoria university of wellington)\b",
        org,
        re.IGNORECASE,
    ):
        return "New Zealand"

    return ""


def normalize_delegate_records(
    delegates: pd.DataFrame,
    *,
    apply_overrides: bool = True,
) -> pd.DataFrame:
    """Repair merged organisation fields from the delegate PDF layout."""
    delegates = delegates.copy()
    for index, row in delegates.iterrows():
        organisation = organisation_for_delegate_row(
            row, apply_overrides=apply_overrides
        )
        country = str(row.get("country") or "").strip()
        if apply_overrides:
            country_override = country_override_for_row(row)
            if country_override:
                country = country_override
        if not country:
            country = infer_country_from_organisation(organisation)
        affiliation = delegate_affiliation_for_row(
            {
                "organisation": organisation,
                "country": country,
                "affiliation": row.get("affiliation"),
                "first_name": row.get("first_name"),
                "last_name": row.get("last_name"),
                "full_name": row.get("full_name"),
            },
            apply_overrides=False,
        )
        delegates.at[index, "organisation"] = organisation
        delegates.at[index, "country"] = country
        delegates.at[index, "affiliation"] = affiliation
        if country:
            delegates.at[index, "country_code"] = country_to_iso2(country)
    return delegates


def _load_json(path: Path) -> Any:
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def _save_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, ensure_ascii=True)


def normalize_person_name(value: str) -> str:
    value = TITLE_RE.sub("", str(value).strip().lower())
    value = re.sub(r"[^a-z0-9\s]", " ", value)
    return re.sub(r"\s+", " ", value).strip()


def _resolve_id_match_review_path(path: Path | None = None) -> Path | None:
    if path is not None:
        return path if path.exists() else None
    merged = delegate_id_match_review_files()
    return merged[-1] if merged else None


def load_delegate_person_keys(
    path: Path | str | None = None,
) -> dict[str, str]:
    """Map delegate name variants to stable icrs-p-* person keys."""
    global _DELEGATE_PERSON_KEY_CACHE
    if _DELEGATE_PERSON_KEY_CACHE is not None and path is None:
        return _DELEGATE_PERSON_KEY_CACHE

    from src.registry.person_registry import DEFAULT_ALIASES_PATH, load_name_aliases

    aliases_path = Path(path) if path is not None else DEFAULT_ALIASES_PATH
    aliases = load_name_aliases(aliases_path)
    mapping: dict[str, str] = {}
    for _, row in aliases.iterrows():
        person_key = str(row.get("person_key") or "").strip()
        if not person_key:
            continue
        for column in ("name_variant", "normalized_name"):
            name = str(row.get(column) or "").strip()
            if not name:
                continue
            mapping[name.casefold()] = person_key
            if column == "name_variant":
                norm = normalize_person_name(name)
                if norm:
                    mapping[norm] = person_key

    if path is None:
        _DELEGATE_PERSON_KEY_CACHE = mapping
    return mapping


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


PRESENTER_NODE_SEP = "\x1f"


def normalize_organisation_label(value: str) -> str:
    return normalize_person_name(str(value or "").replace(",", " "))


def presenter_identity_node(presenter_norm: str, affiliation: str = "") -> str:
    aff_norm = normalize_organisation_label(affiliation)
    if aff_norm:
        return f"{presenter_norm}{PRESENTER_NODE_SEP}{aff_norm}"
    return presenter_norm


def register_talk_presenters(
    talks: pd.DataFrame,
    *,
    presenter_display: dict[str, str],
    uf: _UnionFind,
    token_index: dict[str, set[str]],
) -> None:
    """Index programme presenters by name tokens and affiliation for homonym disambiguation."""
    for _, talk in talks.iterrows():
        presenter = str(talk.get("presenter") or "").strip()
        if not presenter:
            continue
        affiliation = str(talk.get("affiliation") or "").strip()
        norm = normalize_person_name(presenter)
        node = presenter_identity_node(norm, affiliation)
        presenter_display[node] = presenter
        uf.find(node)
        for token in name_tokens(presenter):
            token_index.setdefault(token, set()).add(node)


def match_delegate_to_presenter_node(
    delegate_name: str,
    delegate_organisation: str,
    token_index: dict[str, set[str]],
    presenter_display: dict[str, str],
) -> str | None:
    """Match a delegate-list name to a programme presenter without merging homonyms."""
    delegate_tokens = name_tokens(delegate_name)
    if not delegate_tokens:
        return None
    # Ignore honorific tokens (e.g. "prof" in "A/Prof …") that are not in the index.
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
        org_matches = [
            node
            for node in filtered
            if PRESENTER_NODE_SEP in node
            and node.split(PRESENTER_NODE_SEP, 1)[1] == org_norm
        ]
        if len(org_matches) == 1:
            return org_matches[0]
    return None


def _match_single_presenter_norm(
    name: str,
    token_index: dict[str, set[str]],
) -> str | None:
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


def _register_name_variants(
    variant_to_key: dict[str, str],
    *,
    person_key: str,
    names: set[str],
) -> None:
    for name in names:
        cleaned = str(name or "").strip()
        if not cleaned:
            continue
        for variant in {cleaned, cleaned.casefold(), normalize_person_name(cleaned)}:
            if variant:
                variant_to_key[variant] = person_key


def load_person_identity_maps(
    *,
    delegates: pd.DataFrame | None = None,
    talks: pd.DataFrame | None = None,
    id_keys_path: Path | str | None = None,
    use_cache: bool = True,
    show_progress: bool = False,
) -> tuple[dict[str, str], dict[str, str]]:
    """Map name variants to a stable person key and preferred display name.

    Talk presenter names are preferred over delegate-list spellings when the
    same person is matched via token overlap or delegate-id review.
    """
    global _PERSON_IDENTITY_CACHE
    cacheable = (
        use_cache
        and delegates is None
        and talks is None
        and id_keys_path is None
    )
    if cacheable and _PERSON_IDENTITY_CACHE is not None:
        return _PERSON_IDENTITY_CACHE

    if talks is None:
        talks = load_talks()
    if delegates is None:
        delegates = load_delegates()

    uf = _UnionFind()
    presenter_display: dict[str, str] = {}
    delegate_display: dict[str, str] = {}
    id_key_by_norm: dict[str, str] = {}

    token_index: dict[str, set[str]] = {}
    register_talk_presenters(
        talks,
        presenter_display=presenter_display,
        uf=uf,
        token_index=token_index,
    )

    id_mapping = load_delegate_person_keys(id_keys_path)
    id_variants_by_key: dict[str, list[str]] = {}
    for variant, person_key in id_mapping.items():
        id_variants_by_key.setdefault(person_key, []).append(variant)

    for variants in id_variants_by_key.values():
        norms = [
            normalize_person_name(variant) or variant.strip().casefold()
            for variant in variants
            if str(variant).strip()
        ]
        if not norms:
            continue
        root = norms[0]
        uf.find(root)
        for norm in norms[1:]:
            uf.union(root, norm)

    for person_key, variants in id_variants_by_key.items():
        for variant in variants:
            variant_norm = normalize_person_name(variant) or variant.strip().casefold()
            if variant_norm:
                id_key_by_norm[uf.find(variant_norm)] = person_key

    from src.site.export_progress import iterrows_with_progress

    for _, row in iterrows_with_progress(
        delegates,
        "Linking delegate names to talk presenters",
        show_progress=show_progress,
    ):
        full_name = str(row.get("full_name") or "").strip()
        if not full_name:
            continue
        norm = str(row.get("norm_name") or normalize_person_name(full_name))
        delegate_display[norm] = full_name
        uf.find(norm)

        organisation = delegate_org_country_for_row(row)[0]
        matched_presenter = match_delegate_to_presenter_node(
            full_name,
            organisation,
            token_index,
            presenter_display,
        )
        if matched_presenter:
            uf.union(norm, matched_presenter)

    components: dict[str, set[str]] = {}
    for node in uf.parent:
        components.setdefault(uf.find(node), set()).add(node)

    variant_to_key: dict[str, str] = {}
    key_to_canonical: dict[str, str] = {}
    for members in components.values():
        delegate_ids = {
            id_key_by_norm[member]
            for member in members
            if member in id_key_by_norm
        }
        presenter_members = sorted(
            member for member in members if member in presenter_display
        )
        delegate_members = sorted(
            member for member in members if member in delegate_display
        )
        person_key = (
            sorted(delegate_ids)[0]
            if delegate_ids
            else presenter_members[0]
            if presenter_members
            else sorted(members)[0]
        )
        if presenter_members:
            canonical = presenter_display[presenter_members[0]]
        elif delegate_members:
            canonical = delegate_display[delegate_members[0]]
        else:
            canonical = person_key

        key_to_canonical[person_key] = canonical
        names = {canonical}
        for member in presenter_members:
            names.add(presenter_display[member])
        for member in delegate_members:
            names.add(delegate_display[member])
        _register_name_variants(variant_to_key, person_key=person_key, names=names)

    if cacheable:
        _PERSON_IDENTITY_CACHE = (variant_to_key, key_to_canonical)
    return variant_to_key, key_to_canonical


def delegate_person_key(name: str) -> str:
    """Return a stable person key for deduplicating delegate name variants."""
    cleaned = str(name or "").strip()
    if not cleaned:
        return ""
    variant_to_key, _ = load_person_identity_maps()
    return (
        variant_to_key.get(normalize_person_name(cleaned))
        or variant_to_key.get(cleaned.casefold())
        or variant_to_key.get(cleaned)
        or normalize_person_name(cleaned)
    )


def canonical_person_name(name: str) -> str:
    """Return the preferred display name for a person across talk/delegate aliases."""
    cleaned = str(name or "").strip()
    if not cleaned:
        return ""
    _, key_to_canonical = load_person_identity_maps()
    person_key = delegate_person_key(cleaned)
    return key_to_canonical.get(person_key, cleaned)


def name_tokens(value: str) -> set[str]:
    return {token for token in normalize_person_name(value).split() if len(token) > 1}


def repair_mojibake(text: str) -> str:
    """Repair UTF-8 text that was mis-decoded as MacRoman (√≥ → ó, etc.)."""
    value = str(text or "")
    if not value or not _MOJIBAKE_MARKERS_RE.search(value):
        return value
    try:
        repaired = value.encode("mac_roman").decode("utf-8")
    except UnicodeError:
        return value
    if repaired.count("�") >= value.count("�"):
        return repaired
    return value


def country_to_iso2(country_name: str) -> str:
    cleaned = repair_mojibake(str(country_name)).strip()
    if not cleaned:
        return ""
    alias = COUNTRY_ALIASES.get(cleaned.casefold())
    lookup_name = alias or cleaned
    # Map display aliases back to pycountry names where needed.
    pycountry_names = {
        "South Korea": "Korea, Republic of",
        "United States Virgin Islands": "Virgin Islands, U.S.",
        "Sint Maarten": "Sint Maarten (Dutch part)",
        "Curaçao": "Curaçao",
    }
    lookup_name = pycountry_names.get(lookup_name, lookup_name)
    try:
        return pycountry.countries.lookup(lookup_name).alpha_2
    except LookupError:
        # Last-resort direct alias ISO map for awkward territories.
        direct = {
            "south korea": "KR",
            "korea, republic of": "KR",
            "sint maarten": "SX",
            "united states virgin islands": "VI",
            "virgin islands (u.s.)": "VI",
            "northern mariana islands": "MP",
            "micronesia, federated states of": "FM",
            "curaçao": "CW",
            "curacao": "CW",
        }
        return direct.get(cleaned.casefold(), "")


def extract_layout_text(
    pdf_path: Path = DEFAULT_DELEGATE_PDF_PATH,
    *,
    cache_path: Path = DEFAULT_DELEGATES_LAYOUT_CACHE,
    refresh: bool = False,
) -> str:
    pdf_path = Path(pdf_path)
    cache_path = Path(cache_path)
    if (
        not refresh
        and cache_path.exists()
        and cache_path.stat().st_mtime >= pdf_path.stat().st_mtime
    ):
        return repair_mojibake(cache_path.read_text(encoding="utf-8"))

    result = subprocess.run(
        ["pdftotext", "-enc", "UTF-8", "-layout", str(pdf_path), "-"],
        check=True,
        capture_output=True,
    )
    text = repair_mojibake(result.stdout.decode("utf-8"))
    cache_path.write_text(text, encoding="utf-8")
    return text


def _known_country_suffixes() -> list[str]:
    global _COUNTRY_SUFFIXES
    if _COUNTRY_SUFFIXES is not None:
        return _COUNTRY_SUFFIXES

    names = set(_EXTRA_COUNTRY_NAMES)
    names.update(country.name for country in pycountry.countries)
    names.update(COUNTRY_ALIASES.keys())
    names.update(COUNTRY_ALIASES.values())
    # Title-case alias keys so endswith checks against PDF text still work.
    names.update(
        " ".join(part.capitalize() for part in key.split()) for key in COUNTRY_ALIASES
    )
    _COUNTRY_SUFFIXES = sorted(names, key=len, reverse=True)
    return _COUNTRY_SUFFIXES


def _canonicalize_country(name: str) -> str:
    cleaned = repair_mojibake(name).strip()
    if not cleaned:
        return ""
    alias = COUNTRY_ALIASES.get(cleaned.casefold())
    if alias:
        return alias
    for known in _known_country_suffixes():
        if known.casefold() == cleaned.casefold():
            return known
    return cleaned


def _match_country_label(text: str) -> tuple[str | None, bool]:
    """Return (country_label, needs_wrap_continuation)."""
    cleaned = repair_mojibake(text).strip().rstrip(",")
    if not cleaned or len(cleaned) < 2:
        return None, False

    if country_to_iso2(cleaned):
        return _canonicalize_country(cleaned), False

    fold = cleaned.casefold()
    prefix_hits = [
        name
        for name in _known_country_suffixes()
        if name.casefold().startswith(fold) and len(cleaned) >= 6
    ]
    # Prefer exact official / alias forms over random capitalizations.
    prefix_hits = sorted(set(prefix_hits), key=lambda item: (len(item), item))
    if len(prefix_hits) == 1:
        label = _canonicalize_country(prefix_hits[0])
        return label, label.casefold() != fold and not fold.endswith(
            label.casefold().split()[-1]
        )
    if len(prefix_hits) > 1:
        # Unique canonical form?
        canon = {_canonicalize_country(item) for item in prefix_hits}
        if len(canon) == 1:
            label = next(iter(canon))
            return label, True
        label = _canonicalize_country(prefix_hits[0])
        return label, True

    if fold.startswith("micronesia"):
        return "Micronesia, Federated States of", True
    if fold.startswith("northern mariana"):
        return "Northern Mariana Islands", True
    if fold.startswith("venezuela"):
        return "Venezuela, Bolivarian Republic of", True
    if fold.startswith("tanzania"):
        return "Tanzania, United Republic of", True
    if fold.startswith("bolivia"):
        return "Bolivia, Plurinational State of", True

    return None, False


def _country_is_incomplete(label: str) -> bool:
    cleaned = repair_mojibake(label).strip()
    if not cleaned:
        return False
    fold = cleaned.casefold()
    if fold in {
        "northern mariana",
        "micronesia (the",
        "venezuela, bolivarian",
        "tanzania, united",
        "bolivia, plurinational",
    }:
        return True
    matched, incomplete = _match_country_label(cleaned)
    if matched and incomplete:
        return True
    # Recognized full forms are complete.
    if matched and country_to_iso2(matched):
        return False
    # Unmatched trailing fragments that look like wrapped official names.
    return cleaned.endswith((",", "(")) or fold.endswith("(the")


def _merge_wrapped_country(existing: str, addition: str) -> str:
    existing = repair_mojibake(existing).strip()
    addition = repair_mojibake(addition).strip()
    if not addition:
        return existing
    if not existing:
        matched, _ = _match_country_label(addition)
        return matched or addition

    candidates = [
        f"{existing} {addition}",
        f"{existing}{addition}",
        re.sub(r"\s+", " ", f"{existing} {addition}").strip(),
    ]
    # "Micronesia (the" + "Federated States of)" → normalize punctuation.
    candidates.append(
        re.sub(r"\s+", " ", f"{existing} {addition}").replace(" )", ")").strip()
    )
    for candidate in candidates:
        matched, incomplete = _match_country_label(candidate)
        if matched and not incomplete and country_to_iso2(matched):
            return matched
        if country_to_iso2(candidate):
            return _canonicalize_country(candidate)

    matched, _ = _match_country_label(f"{existing} {addition}".strip())
    return matched or f"{existing} {addition}".strip()


def _layout_fields(line: str) -> list[tuple[int, str]]:
    """Split a layout line into columns; only single spaces allowed within a field."""
    return [
        (match.start(), match.group())
        for match in re.finditer(r"\S+(?: \S+)*(?=\s{2,}|\s*$)", line)
    ]


def _is_skippable_layout_line(line: str) -> bool:
    if not line.startswith("    ") or not line.strip():
        return True
    markers = (
        "First name",
        "List of Delegates",
        "Excluding those",
        "Created ",
    )
    if any(marker in line for marker in markers):
        return True
    return line.strip().startswith("Page:")


def _extract_country_suffix(line: str) -> tuple[str | None, str]:
    """Backward-compatible helper: split a person line into country + prefix."""
    stripped = repair_mojibake(line).rstrip()
    fields = _layout_fields(stripped)
    if len(fields) >= 3:
        country_text = fields[-1][1]
        matched, incomplete = _match_country_label(country_text)
        if matched and not incomplete:
            prefix_end = fields[-1][0]
            return matched, stripped[:prefix_end].rstrip()
        if matched and incomplete:
            prefix_end = fields[-1][0]
            return country_text, stripped[:prefix_end].rstrip()

    country_col = stripped[COL_COUNTRY:].strip() if len(stripped) > COL_COUNTRY else ""
    matched, incomplete = _match_country_label(country_col)
    if matched and not incomplete:
        return matched, stripped[:COL_COUNTRY].rstrip()

    tail = stripped[COL_ORG:].rstrip() if len(stripped) > COL_ORG else stripped
    for country in _known_country_suffixes():
        if not tail.endswith(country):
            continue
        index = stripped.rfind(country)
        if index < COL_ORG - 15:
            continue
        if not country_to_iso2(country):
            continue
        prefix = stripped[:index].rstrip()
        if len(prefix) < 8:
            continue
        return _canonicalize_country(country), prefix
    return None, stripped


def _parse_name_org(prefix: str) -> tuple[str, str, str]:
    parts = [
        part.strip()
        for part in re.split(r"\s{2,}", repair_mojibake(prefix).strip())
        if part.strip()
    ]
    if len(parts) >= 3:
        return parts[0], parts[1], " ".join(parts[2:])
    if len(parts) == 2:
        return parts[0], "", parts[1]
    if len(parts) == 1:
        return parts[0], "", ""
    return "", "", ""


def _parse_person_layout_line(line: str) -> dict[str, Any]:
    stripped = repair_mojibake(line).rstrip()
    fields = _layout_fields(stripped)
    first = stripped[COL_FIRST:COL_LAST].strip() if len(stripped) > COL_FIRST else ""

    # Drop the first-name field; remainder starts at last name or organisation.
    if fields and fields[0][0] < COL_LAST:
        rest = fields[1:]
    else:
        rest = fields

    last = ""
    remainder = rest
    if rest and rest[0][0] < _ORG_COL_MIN:
        last = rest[0][1]
        remainder = rest[1:]

    organisation = ""
    country = ""
    country_incomplete = False

    if remainder:
        country_text = remainder[-1][1]
        matched, incomplete = _match_country_label(country_text)
        if matched:
            country = country_text if incomplete else matched
            country_incomplete = incomplete or _country_is_incomplete(country_text)
            organisation = " ".join(text for _, text in remainder[:-1]).strip()
        else:
            organisation = " ".join(text for _, text in remainder).strip()

    organisation = re.sub(r"\s+", " ", organisation).strip()
    return {
        "first_name": first,
        "last_name": last,
        "organisation": organisation,
        "country": country,
        "_country_incomplete": country_incomplete,
        "_org_incomplete": is_incomplete_organisation(organisation),
    }


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
        addition = " ".join(country_bits)
        current["country"] = _merge_wrapped_country(
            str(current.get("country") or ""), addition
        )
        current["_country_incomplete"] = _country_is_incomplete(
            str(current.get("country") or "")
        )
    if org_bits:
        addition = " ".join(org_bits)
        merged = f"{current.get('organisation', '')} {addition}".strip()
        current["organisation"] = re.sub(r"\s+", " ", merged)
        current["_org_incomplete"] = is_incomplete_organisation(current["organisation"])


def parse_delegate_layout_text(text: str) -> pd.DataFrame:
    """Parse pdftotext -layout output into delegate records."""
    records: list[dict[str, str]] = []
    current: dict[str, Any] | None = None
    ignore_continuations = False

    def flush() -> None:
        nonlocal current
        if current is None:
            return
        record = {
            "first_name": str(current.get("first_name") or "").strip(),
            "last_name": str(current.get("last_name") or "").strip(),
            "organisation": re.sub(
                r"\s+", " ", str(current.get("organisation") or "")
            ).strip(),
            "country": _canonicalize_country(str(current.get("country") or "")),
        }
        records.append(record)
        current = None

    for raw_line in repair_mojibake(text).splitlines():
        line = raw_line.rstrip("\n")
        if _is_skippable_layout_line(line):
            if any(
                marker in line
                for marker in ("First name", "List of Delegates", "Page:")
            ):
                ignore_continuations = True
            continue

        first = line[COL_FIRST:COL_LAST].strip() if len(line) > COL_FIRST else ""
        if first:
            flush()
            ignore_continuations = False
            current = _parse_person_layout_line(line)
            continue

        if current is None or ignore_continuations:
            continue

        # Accept wraps for incomplete org/country, or clearly country-column text.
        fields = _layout_fields(line)
        has_country_col = any(start >= _COUNTRY_COL_MIN for start, _ in fields)
        if (
            current.get("_org_incomplete")
            or current.get("_country_incomplete")
            or has_country_col
        ):
            _append_continuation(current, line)

    flush()

    if not records:
        return pd.DataFrame(
            columns=[
                "first_name",
                "last_name",
                "organisation",
                "country",
                "full_name",
                "affiliation",
            ]
        )

    df = pd.DataFrame(records)
    df["full_name"] = (
        df["first_name"].str.strip() + " " + df["last_name"].str.strip()
    ).str.strip()
    # Fresh PDF parses should not reuse stale organisation overrides that were
    # authored against earlier merged-row extraction bugs.
    df = normalize_delegate_records(df, apply_overrides=False)
    df["country_code"] = df["country"].map(country_to_iso2)
    # Keep rows even when country is missing so PDF gaps remain visible for review.
    return df


def load_delegates(
    *,
    pdf_path: Path = DEFAULT_DELEGATE_PDF_PATH,
    json_path: Path = DEFAULT_DELEGATES_JSON_PATH,
    refresh: bool = False,
) -> pd.DataFrame:
    pdf_path = Path(pdf_path)
    json_path = Path(json_path)
    if (
        json_path.exists()
        and not refresh
        and (
            not pdf_path.exists()
            or json_path.stat().st_mtime >= pdf_path.stat().st_mtime
        )
    ):
        payload = _load_json(json_path)
        # JSON is already cleaned at save time; do not re-apply organisation
        # overrides here (many predate the layout-parser fix and are stale).
        return normalize_delegate_records(
            pd.DataFrame(payload["delegates"]), apply_overrides=False
        )

    if not pdf_path.exists():
        if json_path.exists():
            payload = _load_json(json_path)
            return normalize_delegate_records(
                pd.DataFrame(payload["delegates"]), apply_overrides=False
            )
        raise FileNotFoundError(
            f"Delegate PDF not found: {pdf_path}. "
            f"Place the list PDF there or keep {json_path} up to date."
        )

    text = extract_layout_text(pdf_path, refresh=refresh)
    delegates = parse_delegate_layout_text(text)
    delegates = mark_delegate_speakers(delegates)
    save_delegates(delegates, json_path=json_path, source_pdf=pdf_path)
    return delegates


def mark_delegate_speakers(delegates: pd.DataFrame) -> pd.DataFrame:
    talks = load_talks()
    presenters = (
        talks[["presenter"]]
        .dropna()
        .drop_duplicates()
        .assign(norm=lambda frame: frame["presenter"].map(normalize_person_name))
    )
    presenter_norms = set(presenters["norm"])
    presenter_tokens = presenters["norm"].map(name_tokens).tolist()

    delegates = delegates.copy()
    delegates["norm_name"] = delegates["full_name"].map(normalize_person_name)
    delegates["is_speaker"] = delegates["norm_name"].isin(presenter_norms)

    token_index: dict[str, set[str]] = {}
    for norm, tokens in zip(presenters["norm"], presenter_tokens, strict=False):
        for token in tokens:
            token_index.setdefault(token, set()).add(norm)

    for index, row in delegates.loc[~delegates["is_speaker"]].iterrows():
        tokens = name_tokens(row["full_name"])
        if not tokens:
            continue
        candidate_norms: set[str] | None = None
        for token in tokens:
            matches = token_index.get(token)
            if not matches:
                candidate_norms = None
                break
            candidate_norms = (
                matches if candidate_norms is None else candidate_norms & matches
            )
        if candidate_norms and len(candidate_norms) == 1:
            delegates.at[index, "is_speaker"] = True

    return delegates


def delegate_list_groups(
    delegates: pd.DataFrame | None = None,
    *,
    variant_to_key: dict[str, str] | None = None,
    show_progress: bool = False,
) -> list[dict[str, Any]]:
    """Group all delegate-list attendees by affiliation for the map site."""
    from src.geocoding.geocode import affiliation_display_name, canonical_affiliation_key
    from src.site.export_progress import iterrows_with_progress
    from src.site.map_exclusions import is_map_excluded, load_map_exclusions

    if delegates is None:
        delegates = load_delegates()

    map_exclusions = load_map_exclusions()
    if variant_to_key is None:
        variant_to_key, _ = load_person_identity_maps(delegates=delegates)
    groups: dict[str, dict[str, Any]] = {}
    for _, row in iterrows_with_progress(
        delegates,
        "Grouping delegates by affiliation",
        show_progress=show_progress,
    ):
        affiliation = delegate_affiliation_for_row(row)
        if not affiliation:
            continue
        name = str(row.get("full_name") or "").strip()
        if not name or is_map_excluded(name, set(map_exclusions.names)):
            continue
        display = affiliation_display_name(
            affiliation
        ) or organisation_for_delegate_row(row)
        if is_incomplete_organisation(display):
            continue
        key = canonical_affiliation_key(affiliation).casefold()
        group = groups.setdefault(
            key,
            {
                "affiliation_key": key,
                "affiliation": display,
                "delegates": [],
            },
        )
        if len(display) > len(group["affiliation"]):
            group["affiliation"] = display
        country = str(row.get("country") or "").strip()
        person_key = (
            variant_to_key.get(normalize_person_name(name))
            or variant_to_key.get(name.casefold())
            or variant_to_key.get(name)
            or normalize_person_name(name)
        )
        group["delegates"].append(
            {
                "name": name,
                "search_text": " ".join(
                    part for part in (name, display, country) if part
                ).lower(),
                "is_speaker": bool(row.get("is_speaker")),
                "person_key": person_key,
            }
        )

    for group in groups.values():
        group["delegates"].sort(key=lambda item: item["name"].casefold())

    return sorted(groups.values(), key=lambda item: item["affiliation"].casefold())


def non_speaking_delegate_groups(
    delegates: pd.DataFrame | None = None,
) -> list[dict[str, Any]]:
    """Backwards-compatible alias for delegate_list_groups."""
    return delegate_list_groups(delegates)


def export_non_speaking_delegates_js(
    save_path: str | Path = "js/non-speaking-delegates.js",
    *,
    delegates: pd.DataFrame | None = None,
    show_progress: bool = False,
) -> Path:
    """Export delegate-list groups and name→person_key aliases for the map site."""
    variant_to_key, key_to_canonical = load_person_identity_maps(
        delegates=delegates,
        show_progress=show_progress,
    )
    groups = delegate_list_groups(
        delegates,
        variant_to_key=variant_to_key,
        show_progress=show_progress,
    )
    output_path = Path(save_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    body = (
        "/** Generated from data/sources/delegates.json – do not edit by hand. */\n"
        f"export const NON_SPEAKING_DELEGATE_GROUPS = {json.dumps(groups, ensure_ascii=False, indent=2)};\n"
        f"export const DELEGATE_PERSON_KEY_ALIASES = {json.dumps(variant_to_key, ensure_ascii=False, indent=2)};\n"
        f"export const PERSON_CANONICAL_NAMES = {json.dumps(key_to_canonical, ensure_ascii=False, indent=2)};\n"
    )
    output_path.write_text(body, encoding="utf-8")
    return output_path


def save_delegates(
    delegates: pd.DataFrame,
    *,
    json_path: Path = DEFAULT_DELEGATES_JSON_PATH,
    source_pdf: Path = DEFAULT_DELEGATE_PDF_PATH,
) -> Path:
    payload = {
        "meta": {
            "source_pdf": str(source_pdf),
            "delegate_count": len(delegates),
            "speaker_count": int(delegates["is_speaker"].sum()),
            "non_speaker_count": int((~delegates["is_speaker"]).sum()),
        },
        "delegates": delegates.to_dict(orient="records"),
    }
    _save_json(Path(json_path), payload)
    return Path(json_path)


def _fill_missing_with_capital_fallback(rows: pd.DataFrame) -> pd.DataFrame:
    """Use state/country capitals when institute geocoding is missing."""
    from src.geocoding.capital_coords import resolve_capital_fallback

    rows = rows.copy()
    missing_mask = rows["latitude"].isna() | rows["longitude"].isna()
    if not missing_mask.any():
        return rows

    for index, row in rows.loc[missing_mask].iterrows():
        country = str(row.get("country") or "").strip()
        if not country:
            continue
        organisation = str(row.get("organisation") or "").strip()
        fallback = resolve_capital_fallback(organisation, country)
        if fallback is None:
            continue
        _city, lat, lon, query_label = fallback
        rows.at[index, "latitude"] = lat
        rows.at[index, "longitude"] = lon
        rows.at[index, "geocode_level"] = "country"
        rows.at[index, "geocoded"] = True
        rows.at[index, "query_used"] = query_label

    return rows


def geocoded_delegate_list(
    delegates: pd.DataFrame | None = None,
    *,
    show_progress: bool = False,
) -> pd.DataFrame:
    """Return geocoded rows for every delegate on the published list."""
    from src.geocoding.affiliation_geocodes import (
        build_geocode_lookup,
        load_geocode_overrides,
        load_ok_geocodes,
        resolve_geocode,
    )

    if delegates is None:
        delegates = load_delegates()

    if delegates.empty:
        return pd.DataFrame(
            columns=[
                "presenter",
                "affiliation",
                "latitude",
                "longitude",
                "geocode_level",
                "country",
                "country_code",
            ]
        )

    rows = delegates.rename(columns={"full_name": "presenter"}).copy()
    rows["affiliation"] = rows.apply(delegate_affiliation_for_row, axis=1)
    rows["latitude"] = pd.NA
    rows["longitude"] = pd.NA
    rows["geocode_level"] = pd.NA
    rows["geocoded"] = False
    rows["query_used"] = pd.NA

    lookup = build_geocode_lookup(load_ok_geocodes())
    overrides = load_geocode_overrides()
    from src.registry.affiliation_lookup import AffiliationIndex, registry_geocode_hit

    affiliation_index = AffiliationIndex.load()
    from src.site.export_progress import iterrows_with_progress

    for index, row in iterrows_with_progress(
        rows,
        "Geocoding delegate list",
        show_progress=show_progress,
    ):
        hit = resolve_geocode(
            str(row["affiliation"]),
            presenter=str(row["presenter"]),
            lookup=lookup,
            overrides=overrides,
        )
        if hit is None:
            from src.registry.affiliation_registry import parse_affiliation_parts

            organisation, country = parse_affiliation_parts(str(row["affiliation"]))
            hit = registry_geocode_hit(organisation, country, index=affiliation_index)
        if hit is None:
            continue
        rows.at[index, "latitude"] = float(hit["latitude"])
        rows.at[index, "longitude"] = float(hit["longitude"])
        rows.at[index, "geocode_level"] = hit.get("geocode_level")
        rows.at[index, "geocoded"] = True
        rows.at[index, "query_used"] = hit.get("query_used")

    rows = _fill_missing_with_capital_fallback(rows)
    if "country_code" not in rows.columns:
        rows["country_code"] = rows["country"].map(country_to_iso2)
    if show_progress:
        geocoded_count = rows.dropna(subset=["latitude", "longitude"]).shape[0]
        print(f"Delegate list geocoded: {geocoded_count:,} of {len(rows):,}")
    return rows


def geocoded_non_speakers(
    delegates: pd.DataFrame | None = None,
    *,
    show_progress: bool = False,
) -> pd.DataFrame:
    """Backwards-compatible alias for geocoded_delegate_list."""
    return geocoded_delegate_list(delegates, show_progress=show_progress)


def combined_attendee_talks(
    talks_geo: pd.DataFrame,
    *,
    include_non_speakers: bool = False,
    delegates: pd.DataFrame | None = None,
    show_progress: bool = False,
) -> pd.DataFrame:
    """Speaker geocodes from talks, optionally plus non-speaking delegates."""
    if not include_non_speakers:
        return talks_geo

    from src.site.export_progress import console, run_with_progress

    if show_progress:
        console().print("  Geocoding delegate list")
    extra = geocoded_delegate_list(delegates, show_progress=show_progress)

    if show_progress:
        console().print("  Warming person-identity cache")
    variant_to_key, _ = load_person_identity_maps()

    def _person_key(name: object) -> str:
        cleaned = str(name or "").strip()
        if not cleaned:
            return ""
        return (
            variant_to_key.get(normalize_person_name(cleaned))
            or variant_to_key.get(cleaned.casefold())
            or variant_to_key.get(cleaned)
            or normalize_person_name(cleaned)
        )

    def _enrich_talks_from_delegates(
        frame: pd.DataFrame, delegate_rows: pd.DataFrame
    ) -> pd.DataFrame:
        talks_out = frame.copy()
        geo_columns = (
            "latitude",
            "longitude",
            "geocode_level",
            "geocoded",
            "query_used",
            "country_code",
        )
        for col in geo_columns:
            if col not in talks_out.columns:
                talks_out[col] = pd.NA
        if "affiliation" not in talks_out.columns:
            talks_out["affiliation"] = pd.NA

        delegate_rows = delegate_rows.dropna(subset=["presenter"]).copy()
        if delegate_rows.empty:
            return talks_out

        delegate_rows["_person_key"] = delegate_rows["presenter"].astype(str).map(_person_key)
        lookup = delegate_rows.drop_duplicates("_person_key", keep="first").set_index("_person_key")
        talks_out["_person_key"] = talks_out["presenter"].astype(str).map(_person_key)

        for index, row in talks_out.iterrows():
            person_key = str(row.get("_person_key") or "").strip()
            if not person_key or person_key not in lookup.index:
                continue
            delegate = lookup.loc[person_key]
            raw_talk_affiliation = row.get("affiliation")
            talk_affiliation = (
                ""
                if pd.isna(raw_talk_affiliation)
                else str(raw_talk_affiliation).strip()
            )
            raw_delegate_affiliation = delegate.get("affiliation")
            delegate_affiliation = (
                ""
                if pd.isna(raw_delegate_affiliation)
                else str(raw_delegate_affiliation).strip()
            )
            if delegate_affiliation and (
                "," in delegate_affiliation
                and ("," not in talk_affiliation or len(delegate_affiliation) > len(talk_affiliation))
            ):
                talks_out.at[index, "affiliation"] = delegate_affiliation

            missing_coords = pd.isna(row.get("latitude")) or pd.isna(row.get("longitude"))
            if not missing_coords:
                continue
            for col in geo_columns:
                if col not in delegate.index:
                    continue
                value = delegate.get(col)
                if pd.notna(value):
                    talks_out.at[index, col] = value
            if pd.notna(talks_out.at[index, "latitude"]):
                talks_out.at[index, "geocoded"] = True

        return talks_out.drop(columns=["_person_key"])

    if show_progress:
        console().print("  Enriching speaker talks from delegate list")
    talks_out = run_with_progress(
        "Applying delegate coordinates to talks",
        lambda: _enrich_talks_from_delegates(talks_geo, extra),
        show_progress=show_progress,
    )

    extra = extra.dropna(subset=["latitude", "longitude"])
    if extra.empty:
        return talks_out

    speaker_cols = [
        "presenter",
        "affiliation",
        "latitude",
        "longitude",
        "geocode_level",
        "country_code",
    ]
    for col in speaker_cols:
        if col not in extra.columns:
            extra[col] = pd.NA

    talk_person_keys = {
        _person_key(name)
        for name in talks_out["presenter"].dropna().astype(str)
        if str(name).strip()
    }
    extra = extra.loc[
        ~extra["presenter"].astype(str).map(_person_key).isin(talk_person_keys)
    ]

    if show_progress:
        console().print(f"  Appending {len(extra):,} delegate-only rows")

    combined = pd.concat(
        [
            talks_out,
            extra[speaker_cols],
        ],
        ignore_index=True,
    )
    combined["_person_key"] = combined["presenter"].astype(str).map(_person_key)
    combined["_has_coords"] = combined["latitude"].notna() & combined["longitude"].notna()
    if show_progress:
        console().print("  Deduplicating combined attendee rows")
    combined = combined.sort_values(
        ["_person_key", "_has_coords", "geocode_level"],
        ascending=[True, False, True],
        na_position="last",
    )
    return combined.drop_duplicates(subset=["_person_key"], keep="first").drop(
        columns=["_person_key", "_has_coords"]
    )
