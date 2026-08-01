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

TITLE_RE = re.compile(r"^(dr|prof|professor|mr|mrs|ms|miss)\.?\s+", re.I)

COUNTRY_ALIASES = {
    "united states": "United States",
    "united kingdom": "United Kingdom",
    "hong kong": "Hong Kong",
    "french polynesia": "French Polynesia",
    "marshall islands": "Marshall Islands",
    "south korea": "Korea, Republic of",
    "republic of korea": "Korea, Republic of",
    "taiwan": "Taiwan",
    "russia": "Russian Federation",
    "vietnam": "Viet Nam",
    "bolivia": "Bolivia, Plurinational State of",
    "iran": "Iran, Islamic Republic of",
    "tanzania": "Tanzania, United Republic of",
    "venezuela": "Venezuela, Bolivarian Republic of",
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
    "federated states of micronesia": "Micronesia, Federated States of",
    "micronesia": "Micronesia, Federated States of",
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


def organisation_for_delegate_row(row: pd.Series | dict[str, Any]) -> str:
    """Resolve the best organisation string for a delegate row."""
    override = organisation_override_for_row(row)
    if override:
        return override
    return sanitize_delegate_organisation(
        str(row.get("organisation") or ""),
        first_name=str(row.get("first_name") or ""),
        last_name=str(row.get("last_name") or ""),
        country=str(row.get("country") or ""),
    )


def delegate_affiliation_for_row(row: pd.Series | dict[str, Any]) -> str:
    """Return a cleaned affiliation string for geocoding and map grouping."""
    if isinstance(row, pd.Series):
        row = row.to_dict()
    organisation = organisation_for_delegate_row(row)
    country = str(row.get("country") or "").strip()
    if organisation and country:
        return f"{organisation}, {country}"
    return organisation or str(row.get("affiliation") or "").strip()


def normalize_delegate_records(delegates: pd.DataFrame) -> pd.DataFrame:
    """Repair merged organisation fields from the delegate PDF layout."""
    delegates = delegates.copy()
    for index, row in delegates.iterrows():
        organisation = organisation_for_delegate_row(row)
        affiliation = delegate_affiliation_for_row(
            {
                "organisation": organisation,
                "country": row.get("country"),
                "affiliation": row.get("affiliation"),
            }
        )
        delegates.at[index, "organisation"] = organisation
        delegates.at[index, "affiliation"] = affiliation
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


def country_to_iso2(country_name: str) -> str:
    cleaned = str(country_name).strip()
    if not cleaned:
        return ""
    alias = COUNTRY_ALIASES.get(cleaned.casefold())
    lookup_name = alias or cleaned
    try:
        return pycountry.countries.lookup(lookup_name).alpha_2
    except LookupError:
        return ""


def extract_layout_text(
    pdf_path: Path = DEFAULT_DELEGATE_PDF_PATH,
    *,
    cache_path: Path = DEFAULT_DELEGATES_LAYOUT_CACHE,
) -> str:
    pdf_path = Path(pdf_path)
    if cache_path.exists() and cache_path.stat().st_mtime >= pdf_path.stat().st_mtime:
        return cache_path.read_text(encoding="utf-8")

    result = subprocess.run(
        ["pdftotext", "-layout", str(pdf_path), "-"],
        check=True,
        capture_output=True,
        text=True,
    )
    cache_path.write_text(result.stdout, encoding="utf-8")
    return result.stdout


def country_to_iso2(country_name: str) -> str:
    cleaned = str(country_name).strip()
    if not cleaned:
        return ""
    alias = COUNTRY_ALIASES.get(cleaned.casefold())
    lookup_name = alias or cleaned
    try:
        return pycountry.countries.lookup(lookup_name).alpha_2
    except LookupError:
        return ""


def _known_country_suffixes() -> list[str]:
    global _COUNTRY_SUFFIXES
    if _COUNTRY_SUFFIXES is not None:
        return _COUNTRY_SUFFIXES

    names = set(_EXTRA_COUNTRY_NAMES)
    names.update(country.name for country in pycountry.countries)
    names.update(COUNTRY_ALIASES.values())
    _COUNTRY_SUFFIXES = sorted(names, key=len, reverse=True)
    return _COUNTRY_SUFFIXES


def _extract_country_suffix(line: str) -> tuple[str | None, str]:
    stripped = line.rstrip()
    country_col = stripped[COL_COUNTRY:].strip() if len(stripped) > COL_COUNTRY else ""
    if country_col and len(country_col) >= 4 and country_to_iso2(country_col):
        return country_col, stripped[:COL_COUNTRY].rstrip()

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
        return country, prefix
    return None, stripped


def _parse_name_org(prefix: str) -> tuple[str, str, str]:
    parts = [
        part.strip() for part in re.split(r"\s{2,}", prefix.strip()) if part.strip()
    ]
    if len(parts) >= 3:
        return parts[0], parts[1], " ".join(parts[2:])
    if len(parts) == 2:
        return parts[0], "", parts[1]
    if len(parts) == 1:
        return parts[0], "", ""
    return "", "", ""


def parse_delegate_layout_text(text: str) -> pd.DataFrame:
    """Parse pdftotext -layout output into delegate records."""
    records: list[dict[str, str]] = []
    current: dict[str, str] | None = None

    for line in text.splitlines():
        if not line.startswith("    ") or not line.strip():
            continue
        if any(
            marker in line
            for marker in (
                "First name",
                "List of Delegates",
                "Excluding those",
                "Created ",
            )
        ) or line.strip().startswith("Page:"):
            continue

        country, prefix = _extract_country_suffix(line)
        if country:
            if current is not None:
                records.append(current)
            first, last, organisation = _parse_name_org(prefix)
            current = {
                "first_name": first,
                "last_name": last,
                "organisation": organisation,
                "country": country,
            }
            continue

        if current is not None:
            continuation = line.strip()
            if continuation:
                current["organisation"] = (
                    f"{current['organisation']} {continuation}".strip()
                )

    if current is not None:
        records.append(current)

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
    df = normalize_delegate_records(df)
    df["country_code"] = df["country"].map(country_to_iso2)
    df = df[df["country_code"].astype(bool)].copy()
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
            return normalize_delegate_records(pd.DataFrame(payload["delegates"]))

    if not pdf_path.exists():
        if json_path.exists():
            payload = _load_json(json_path)
            return normalize_delegate_records(pd.DataFrame(payload["delegates"]))
        raise FileNotFoundError(
            f"Delegate PDF not found: {pdf_path}. "
            f"Place the list PDF there or keep {json_path} up to date."
        )

    text = extract_layout_text(pdf_path)
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


def _resolve_delegate_country_coords(
    country_name: str,
    centroids: dict[str, tuple[float, float]],
) -> tuple[float, float] | None:
    candidates = [country_name.strip()]
    alias = COUNTRY_ALIASES.get(country_name.strip().casefold())
    if alias:
        candidates.append(alias)
    try:
        candidates.append(pycountry.countries.lookup(country_name).name)
    except LookupError:
        pass

    for candidate in candidates:
        if candidate in centroids:
            return centroids[candidate]
    for candidate in candidates:
        for key, coords in centroids.items():
            if key.casefold() == candidate.casefold():
                return coords
    return None


def _fill_missing_with_country_centroids(rows: pd.DataFrame) -> pd.DataFrame:
    """Use delegate-list country when organisation geocoding failed."""
    from geopy.geocoders import Nominatim

    from src.geocode import (
        DEFAULT_COUNTRY_CACHE_PATH,
        DEFAULT_USER_AGENT,
        _ensure_country_coords,
        _load_country_coords_cache,
    )

    rows = rows.copy()
    missing_mask = rows["latitude"].isna() | rows["longitude"].isna()
    if not missing_mask.any():
        return rows

    centroids = _load_country_coords_cache(DEFAULT_COUNTRY_CACHE_PATH)
    missing_countries = (
        rows.loc[missing_mask, "country"].dropna().astype(str).unique().tolist()
    )
    unresolved = [
        country
        for country in missing_countries
        if _resolve_delegate_country_coords(country, centroids) is None
    ]
    if unresolved:
        geolocator = Nominatim(user_agent=DEFAULT_USER_AGENT)
        _ensure_country_coords(
            geolocator,
            unresolved,
            country_coords_cache=centroids,
            country_cache_path=DEFAULT_COUNTRY_CACHE_PATH,
            pause_seconds=1.0,
        )

    for index, row in rows.loc[missing_mask].iterrows():
        coords = _resolve_delegate_country_coords(str(row["country"]), centroids)
        if coords is None:
            continue
        rows.at[index, "latitude"] = coords[0]
        rows.at[index, "longitude"] = coords[1]
        rows.at[index, "geocode_level"] = "country"
        rows.at[index, "geocoded"] = True
        rows.at[index, "query_used"] = f"country:{row['country']}"

    return rows


def geocoded_non_speakers(
    delegates: pd.DataFrame | None = None,
    *,
    show_progress: bool = False,
) -> pd.DataFrame:
    """Return geocoded rows for non-speaking delegates."""
    from src.geocode import geocode_affiliations

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

    unique_affiliations = sorted(
        {aff for aff in rows["affiliation"].dropna().astype(str) if aff.strip()}
    )
    if unique_affiliations:
        geocoded = geocode_affiliations(
            unique_affiliations,
            cache_only=True,
            show_progress=show_progress,
        )
        geo_by_affiliation = {
            str(row["affiliation"]): row for _, row in geocoded.iterrows()
        }
        for index, row in rows.iterrows():
            geo = geo_by_affiliation.get(str(row["affiliation"]))
            if geo is None or pd.isna(geo.get("latitude")) or pd.isna(geo.get("longitude")):
                continue
            rows.at[index, "latitude"] = float(geo["latitude"])
            rows.at[index, "longitude"] = float(geo["longitude"])
            rows.at[index, "geocode_level"] = geo.get("geocode_level")
            rows.at[index, "geocoded"] = True
            rows.at[index, "query_used"] = geo.get("query_used")

    rows = _fill_missing_with_country_centroids(rows)
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
