"""Parse and load the ICRS delegate list."""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path
from typing import Any

import pandas as pd
import pycountry

from src.programme import load_talks

DEFAULT_DELEGATE_PDF_PATH = Path("data/delegate_list_230726.pdf")
DEFAULT_DELEGATES_JSON_PATH = Path("data/delegates.json")
DEFAULT_DELEGATES_LAYOUT_CACHE = Path("data/delegates_layout.txt")
DEFAULT_ORG_OVERRIDES_PATH = Path("data/delegate_organisation_overrides.csv")
DEFAULT_ORG_REVIEW_PATH = Path("data/delegate_organisation_review.csv")

_ORGANISATION_OVERRIDE_CACHE: dict[str, str] | None = None

COL_FIRST = 4
COL_LAST = 32
COL_ORG = 57
COL_COUNTRY = 114
# Layout country text usually begins near here; used for wrap-line routing.
_COUNTRY_COL_MIN = 90
# Last-name column starts at COL_LAST; organisation text is further right.
_ORG_COL_MIN = 45

TITLE_RE = re.compile(r"^(dr|prof|professor|mr|mrs|ms|miss)\.?\s+", re.I)
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
    "Korea, Republic of",
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
    "United States Virgin Islands",
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
    re.I,
)

_BLEED_NAME_RE = re.compile(r"^[A-Z][a-z'`-]+(?:\s+[A-Z][a-z'`-]+){0,2}$")

_TITLE_TOKENS = frozenset(
    {"dr", "prof", "professor", "mr", "mrs", "ms", "miss"}
)

_BLEED_TITLE_NAME_RE = re.compile(
    r"^(.*?)(?:\s+(?:Dr|Prof|Professor|Mr|Mrs|Ms|Miss)\.?\s+[A-Z].*)$",
    re.I,
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
    if len(parts) == 3 and parts[0].casefold() == "university" and parts[1].casefold() == "of":
        if parts[2].casefold() in {
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
        }:
            return True
    return False


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
) -> dict[str, str]:
    """Return manual organisation overrides keyed by normalized person name."""
    global _ORGANISATION_OVERRIDE_CACHE
    if _ORGANISATION_OVERRIDE_CACHE is not None and path == DEFAULT_ORG_OVERRIDES_PATH:
        return _ORGANISATION_OVERRIDE_CACHE

    overrides: dict[str, str] = {}
    if not path.exists():
        _ORGANISATION_OVERRIDE_CACHE = overrides
        return overrides

    frame = pd.read_csv(path)
    for _, row in frame.iterrows():
        organisation = str(row.get("organisation") or "").strip()
        if not organisation:
            continue
        for name_column in ("full_name", "name"):
            name = str(row.get(name_column) or "").strip()
            if not name:
                continue
            overrides[normalize_person_name(name)] = organisation
            overrides[name.casefold()] = organisation

    if path == DEFAULT_ORG_OVERRIDES_PATH:
        _ORGANISATION_OVERRIDE_CACHE = overrides
    return overrides


def organisation_override_for_row(row: pd.Series | dict[str, Any]) -> str | None:
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
    organisation = organisation_for_delegate_row(row, apply_overrides=apply_overrides)
    country = str(row.get("country") or "").strip()
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
    "university of waikato": "New Zealand",
}


def infer_country_from_organisation(organisation: str) -> str:
    """Infer country when the PDF layout truncates before the country column."""
    org = repair_mojibake(str(organisation or "")).strip()
    if not org:
        return ""

    key = re.sub(r"\s+", " ", org).casefold()
    if key in _ORGANISATION_COUNTRY_OVERRIDES:
        return _ORGANISATION_COUNTRY_OVERRIDES[key]

    if re.search(r"hawai['\u2019]?i?\b", org, re.I):
        return "United States"
    if re.search(r"\baustralian\b", org, re.I):
        return "Australia"
    if re.search(
        r"\b(university of auckland|university of waikato|victoria university of wellington)\b",
        org,
        re.I,
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
        " ".join(part.capitalize() for part in key.split())
        for key in COUNTRY_ALIASES
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
    return cleaned.endswith(",") or cleaned.endswith("(") or fold.endswith("(the")


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
        current["_org_incomplete"] = is_incomplete_organisation(
            current["organisation"]
        )


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
    if json_path.exists() and not refresh:
        if not pdf_path.exists() or json_path.stat().st_mtime >= pdf_path.stat().st_mtime:
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
        candidate_norms: set[str] | None = None
        for token in name_tokens(row["full_name"]):
            matches = token_index.get(token)
            if not matches:
                continue
            candidate_norms = (
                matches if candidate_norms is None else candidate_norms & matches
            )
            if candidate_norms and len(candidate_norms) == 1:
                delegates.at[index, "is_speaker"] = True
                break
        if candidate_norms and len(candidate_norms) == 1:
            delegates.at[index, "is_speaker"] = True

    return delegates


def non_speaking_delegate_groups(
    delegates: pd.DataFrame | None = None,
) -> list[dict[str, Any]]:
    """Group non-speaking delegates by affiliation for the map site."""
    from src.geocode import affiliation_display_name, canonical_affiliation_key
    from src.map_exclusions import is_map_excluded, load_map_exclusions

    if delegates is None:
        delegates = load_delegates()

    map_exclusions = load_map_exclusions()
    groups: dict[str, dict[str, Any]] = {}
    non_speakers = delegates.loc[~delegates["is_speaker"]]
    for _, row in non_speakers.iterrows():
        affiliation = delegate_affiliation_for_row(row)
        if not affiliation:
            continue
        name = str(row.get("full_name") or "").strip()
        if not name or is_map_excluded(name, set(map_exclusions.names)):
            continue
        display = affiliation_display_name(affiliation) or organisation_for_delegate_row(row)
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
        group["delegates"].append(
            {
                "name": name,
                "search_text": " ".join(
                    part for part in (name, display, country) if part
                ).lower(),
            }
        )

    for group in groups.values():
        group["delegates"].sort(key=lambda item: item["name"].casefold())

    return sorted(groups.values(), key=lambda item: item["affiliation"].casefold())


def export_non_speaking_delegates_js(
    save_path: str | Path = "js/non-speaking-delegates.js",
    *,
    delegates: pd.DataFrame | None = None,
) -> Path:
    """Export non-speaking delegate names grouped by affiliation."""
    groups = non_speaking_delegate_groups(delegates)
    output_path = Path(save_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    body = (
        "/** Generated from data/delegates.json – do not edit by hand. */\n"
        f"export const NON_SPEAKING_DELEGATE_GROUPS = {json.dumps(groups, ensure_ascii=False, indent=2)};\n"
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
            "delegate_count": int(len(delegates)),
            "speaker_count": int(delegates["is_speaker"].sum()),
            "non_speaker_count": int((~delegates["is_speaker"]).sum()),
        },
        "delegates": delegates.to_dict(orient="records"),
    }
    _save_json(Path(json_path), payload)
    return Path(json_path)


def _fill_missing_with_capital_fallback(rows: pd.DataFrame) -> pd.DataFrame:
    """Use state/country capitals when institute geocoding is missing."""
    from src.capital_coords import resolve_capital_fallback

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


def geocoded_non_speakers(
    delegates: pd.DataFrame | None = None,
    *,
    show_progress: bool = False,
) -> pd.DataFrame:
    """Return geocoded rows for non-speaking delegates."""
    from src.affiliation_geocodes import (
        build_geocode_lookup,
        load_geocode_overrides,
        load_ok_geocodes,
        resolve_geocode,
    )

    if delegates is None:
        delegates = load_delegates()

    non_speakers = delegates.loc[~delegates["is_speaker"]].copy()
    if non_speakers.empty:
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

    rows = non_speakers.rename(columns={"full_name": "presenter"}).copy()
    rows["affiliation"] = rows.apply(delegate_affiliation_for_row, axis=1)
    rows["latitude"] = pd.NA
    rows["longitude"] = pd.NA
    rows["geocode_level"] = pd.NA
    rows["geocoded"] = False
    rows["query_used"] = pd.NA

    lookup = build_geocode_lookup(load_ok_geocodes())
    overrides = load_geocode_overrides()
    for index, row in rows.iterrows():
        hit = resolve_geocode(
            str(row["affiliation"]),
            presenter=str(row["presenter"]),
            lookup=lookup,
            overrides=overrides,
        )
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
        print(f"Non-speaking delegates geocoded: {geocoded_count:,} of {len(rows):,}")
    return rows


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

    extra = geocoded_non_speakers(delegates, show_progress=show_progress)
    extra = extra.dropna(subset=["latitude", "longitude"])
    if extra.empty:
        return talks_geo

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

    combined = pd.concat(
        [
            talks_geo,
            extra[speaker_cols],
        ],
        ignore_index=True,
    )
    combined = combined.sort_values(["presenter", "geocode_level"], na_position="last")
    return combined.drop_duplicates(subset=["presenter"], keep="first")
