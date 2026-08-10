"""Affiliation string helpers: aliases, overrides, query variants, country hints."""

from __future__ import annotations

import re
import unicodedata
from pathlib import Path
from typing import Any

import pycountry

from src.data_paths import AFFILIATION_DISPLAY_ALIASES_JSON, GEOCODE_OVERRIDES_JSON
from src.util.json_io import load_json

DEFAULT_OVERRIDES_PATH = GEOCODE_OVERRIDES_JSON
DEFAULT_DISPLAY_ALIASES_PATH = AFFILIATION_DISPLAY_ALIASES_JSON
_DISPLAY_ALIASES_CACHE: dict[str, str] | None = None
_AFFILIATION_ALIASES: dict[str, str] = {
    "cimas": "University of Miami, Florida",
    "rosenstiel school": "Rosenstiel School University of Miami",
    "umces": "University of Maryland Center for Environmental Sciences, Cambridge, Maryland",
    "institute of marine and environmental technology": "Baltimore, Maryland",
    "moss landing marine laboratories": "Moss Landing Marine Laboratories, California",
    "awi": "Alfred Wegener Institute, Bremerhaven, Germany",
    "cnrs/upvd": "University of Perpignan, France",
    "aoml": "Atlantic Oceanographic and Meteorological Laboratory, Miami, Florida",
    "cordio": "CORDIO East Africa, Mombasa, Kenya",
    "kaust": "KAUST, Saudi Arabia",
    "victoria university of wellington": "Victoria University of Wellington, New Zealand",
    "university of wellington": "Victoria University of Wellington, New Zealand",
    "university of hong kong": "University of Hong Kong, Hong Kong",
    "chinese university of hong kong": "Chinese University of Hong Kong, Hong Kong",
    "university of western australia": "University of Western Australia, Crawley, Perth, Australia",
    "the university of western australia": "University of Western Australia, Crawley, Perth, Australia",
    "james cook university": "James Cook University, Townsville, Queensland, Australia",
    "university of leicester": "University of Leicester, Leicester, United Kingdom",
    "university of auckland": "University of Auckland, Auckland, New Zealand",
    "university of canterbury": "University of Canterbury, Christchurch, New Zealand",
    "auckland university of technology": "Auckland University of Technology, Auckland, New Zealand",
    "western australian museum": "Western Australian Museum, Perth, Western Australia, Australia",
    "department of biodiversity, conservation and attractions": "Department of Biodiversity, Conservation and Attractions, Perth, Western Australia, Australia",
}
_INSTITUTION_GEO_RULES: tuple[tuple[re.Pattern[str], dict[str, Any]], ...] = (
    (
        re.compile(
            "\\b(university of wellington|victoria university of wellington)\\b",
            re.IGNORECASE,
        ),
        {
            "countries": ["New Zealand"],
            "cities": [("Wellington", -41.2889, 174.7762, 90.0)],
            "query": "Victoria University of Wellington, New Zealand",
            "canonical": "Victoria University of Wellington",
        },
    ),
    (
        re.compile("chinese university of hong kong", re.IGNORECASE),
        {
            "countries": ["Hong Kong"],
            "cities": [("Hong Kong", 22.419, 114.206, 80.0)],
            "query": "Chinese University of Hong Kong, Hong Kong",
            "canonical": "Chinese University of Hong Kong",
        },
    ),
    (
        re.compile("(?<!chinese )university of hong kong\\b", re.IGNORECASE),
        {
            "countries": ["Hong Kong"],
            "cities": [("Hong Kong", 22.283, 114.137, 80.0)],
            "query": "University of Hong Kong, Hong Kong",
            "canonical": "University of Hong Kong",
        },
    ),
    (
        re.compile(
            "\\b(university of western australia|the university of western australia)\\b",
            re.IGNORECASE,
        ),
        {
            "countries": ["Australia"],
            "cities": [("Perth", -31.9507, 115.7979, 90.0)],
            "query": "University of Western Australia, Crawley, Perth, Australia",
            "canonical": "University of Western Australia",
        },
    ),
    (
        re.compile("\\bjames cook university\\b", re.IGNORECASE),
        {
            "countries": ["Australia"],
            "cities": [("Townsville", -19.329, 146.757, 120.0)],
            "query": "James Cook University, Townsville, Queensland, Australia",
            "canonical": "James Cook University",
        },
    ),
    (
        re.compile("\\buniversity of leicester\\b", re.IGNORECASE),
        {
            "countries": ["United Kingdom"],
            "cities": [("Leicester", 52.6206, -1.1099, 40.0)],
            "query": "University of Leicester, Leicester, United Kingdom",
            "canonical": "University of Leicester",
        },
    ),
    (
        re.compile("\\buniversity of auckland\\b", re.IGNORECASE),
        {
            "countries": ["New Zealand"],
            "cities": [("Auckland", -36.8661, 174.7737, 90.0)],
            "query": "University of Auckland, Auckland, New Zealand",
            "canonical": "University of Auckland",
        },
    ),
    (
        re.compile("\\buniversity of canterbury\\b", re.IGNORECASE),
        {
            "countries": ["New Zealand"],
            "cities": [("Christchurch", -43.5233, 172.5823, 90.0)],
            "query": "University of Canterbury, Christchurch, New Zealand",
            "canonical": "University of Canterbury",
        },
    ),
    (
        re.compile("\\bauckland university of technology\\b", re.IGNORECASE),
        {
            "countries": ["New Zealand"],
            "cities": [("Auckland", -36.853, 174.7664, 90.0)],
            "query": "Auckland University of Technology, Auckland, New Zealand",
            "canonical": "Auckland University of Technology",
        },
    ),
    (
        re.compile("western australian museum", re.IGNORECASE),
        {
            "countries": ["Australia"],
            "cities": [("Perth", -31.9492, 115.8645, 90.0)],
            "query": "Western Australian Museum, Perth, Australia",
            "canonical": "Western Australian Museum",
        },
    ),
    (
        re.compile(
            "department of biodiversity, conservation and attractions", re.IGNORECASE
        ),
        {
            "countries": ["Australia"],
            "cities": [("Perth", -31.9523, 115.8613, 120.0)],
            "query": "Department of Biodiversity, Conservation and Attractions, Perth, Australia",
            "canonical": "Department of Biodiversity, Conservation and Attractions - Western Australia",
        },
    ),
    (
        re.compile("\\bworld wildlife fund\\b", re.IGNORECASE),
        {
            "countries": ["Australia", "Indonesia", "United States", "United Kingdom"],
            "query": "World Wildlife Fund",
            "canonical": "World Wildlife Fund",
            "regionalize": True,
            "regional_countries": {"Australia": "Australia", "Indonesia": "Indonesia"},
        },
    ),
    (
        re.compile("\\buniversity of south carolina\\b.*\\bbeaufort\\b", re.IGNORECASE),
        {
            "countries": ["United States"],
            "cities": [("Beaufort", 32.4577, -80.6727, 50.0)],
            "query": "University of South Carolina Beaufort, South Carolina, USA",
            "canonical": "University of South Carolina Beaufort",
        },
    ),
    (
        re.compile("\\bcoral restoration foundation\\b", re.IGNORECASE),
        {
            "countries": ["United States"],
            "cities": [("Key Largo", 25.088, -80.441, 80.0)],
            "query": "Coral Restoration Foundation, Key Largo, Florida, USA",
            "canonical": "Coral Restoration Foundation",
        },
    ),
    (
        re.compile("\\bbermuda institute of ocean sciences\\b", re.IGNORECASE),
        {
            "countries": ["Bermuda"],
            "cities": [("St. George's", 32.3708572, -64.6961517, 50.0)],
            "query": "Bermuda Institute of Ocean Sciences, Bermuda",
            "canonical": "Bermuda Institute of Ocean Sciences",
        },
    ),
    (
        re.compile("\\bbangor university\\b", re.IGNORECASE),
        {
            "countries": ["United Kingdom"],
            "cities": [("Bangor", 53.228, -4.129, 40.0)],
            "query": "Bangor University, Bangor, United Kingdom",
            "canonical": "Bangor University",
        },
    ),
    (
        re.compile("\\buniversity of the ryukyus\\b", re.IGNORECASE),
        {
            "countries": ["Japan"],
            "cities": [("Naha", 26.2124, 127.6809, 80.0)],
            "query": "University of the Ryukyus, Okinawa, Japan",
            "canonical": "University of the Ryukyus",
        },
    ),
    (
        re.compile("\\bsouthern cross university\\b", re.IGNORECASE),
        {
            "countries": ["Australia"],
            "cities": [("Lismore", -28.816, 153.283, 120.0)],
            "query": "Southern Cross University, Lismore, Australia",
            "canonical": "Southern Cross University",
        },
    ),
    (
        re.compile("\\bthe nature conservancy\\b", re.IGNORECASE),
        {
            "query": "The Nature Conservancy",
            "canonical": "The Nature Conservancy",
            "regionalize": True,
            "regional_countries": {
                "Federated States of Micronesia": "Micronesia",
                "Guam": "Guam",
                "Jamaica": "Jamaica",
                "Mexico": "Mexico",
                "Micronesia, Federated States of": "Micronesia",
                "Papua New Guinea": "Papua New Guinea",
                "United States": "United States",
                "United States Virgin Islands": "US Virgin Islands",
                "Venezuela, Bolivarian Republic of": "Venezuela",
            },
        },
    ),
)
_COUNTRY_ALIASES: dict[str, str] = {
    "micronesia": "Federated States of Micronesia",
    "micronesian": "Federated States of Micronesia",
    "polynesia": "French Polynesia",
    "polynesian": "French Polynesia",
    "melanesia": "Papua New Guinea",
    "pohnpei": "Pohnpei, Federated States of Micronesia",
    "guam": "Guam",
    "samoa": "Samoa",
    "tahiti": "French Polynesia",
    "moorea": "French Polynesia",
    "virgin islands": "United States Virgin Islands",
    "u.s. virgin islands": "United States Virgin Islands",
    "us virgin islands": "United States Virgin Islands",
    "east africa": "Kenya",
    "west africa": "Senegal",
    "south pacific": "Fiji",
    "caribbean": "Jamaica",
    "india": "India",
    "australia": "Australia",
    "bermuda": "Bermuda",
    "new zealand": "New Zealand",
    "fiji": "Fiji",
    "kenya": "Kenya",
    "madagascar": "Madagascar",
    "indonesia": "Indonesia",
    "philippines": "Philippines",
    "japan": "Japan",
    "china": "China",
    "mexico": "Mexico",
    "brazil": "Brazil",
    "saudi arabia": "Saudi Arabia",
    "south africa": "South Africa",
    "thailand": "Thailand",
    "vietnam": "Vietnam",
    "malaysia": "Malaysia",
    "singapore": "Singapore",
    "hong kong": "Hong Kong",
    "hawaii": "Hawaii, USA",
}
_NORMALIZATIONS = (
    ("\\bOf\\b", "of"),
    ("\\bAnd\\b", "and"),
    ("\\bThe\\b", "the"),
    ("\\s+", " "),
)


def _normalize_text(text: str) -> str:
    text = unicodedata.normalize("NFKD", text)
    text = text.encode("ascii", "ignore").decode("ascii")
    text = text.replace("–", "-").replace("–", "-").strip()
    for pattern, replacement in _NORMALIZATIONS:
        text = re.sub(pattern, replacement, text)
    return text.strip(" ,;-")


def _trailing_country_part_count(parts: list[str]) -> int:
    """Return how many trailing comma-separated parts form a country name."""
    if len(parts) < 2:
        return 0
    from src.sources.delegates import country_to_iso2

    normalized_parts = [_normalize_text(part) for part in parts]
    max_parts = min(4, len(parts) - 1)
    for n in range(max_parts, 0, -1):
        suffix = ", ".join(parts[-n:])
        suffix_norm = ", ".join(normalized_parts[-n:])
        if (
            country_to_iso2(suffix)
            or country_to_iso2(suffix_norm)
            or _lookup_country(suffix_norm)
        ):
            return n
    return 0


def _strip_country_suffix_display(affiliation: str) -> str:
    """Strip a trailing country suffix while preserving Unicode punctuation."""
    text = str(affiliation or "").strip()
    if not text:
        return ""
    parts = [part.strip() for part in text.split(",") if part.strip()]
    trailing = _trailing_country_part_count(parts)
    if trailing:
        return ", ".join(parts[:-trailing]).strip()
    return text


def _clean_affiliation_display(text: str) -> str:
    cleaned = re.sub("\\s+", " ", str(text or "")).strip(" ,;-")
    cleaned = re.sub("\\s*/\\s*$", "", cleaned).strip()
    return cleaned


def affiliation_base_name(affiliation: str) -> str:
    """Strip a trailing country suffix when present."""
    normalized = _normalize_text(affiliation).strip()
    if not normalized:
        return ""
    parts = [part.strip() for part in normalized.split(",") if part.strip()]
    trailing = _trailing_country_part_count(parts)
    if trailing:
        return ", ".join(parts[:-trailing]).strip()
    return normalized


def load_affiliation_display_aliases(
    path: Path = DEFAULT_DISPLAY_ALIASES_PATH,
) -> dict[str, str]:
    global _DISPLAY_ALIASES_CACHE
    if _DISPLAY_ALIASES_CACHE is not None:
        return _DISPLAY_ALIASES_CACHE
    payload = load_json(path, default={})
    aliases = payload.get("aliases") if isinstance(payload, dict) else {}
    if not isinstance(aliases, dict):
        aliases = {}
    _DISPLAY_ALIASES_CACHE = {
        str(key).strip(): str(value).strip()
        for key, value in aliases.items()
        if str(key).strip() and str(value).strip()
    }
    return _DISPLAY_ALIASES_CACHE


def resolve_affiliation_alias(affiliation: str) -> str:
    """Return a reviewed standard affiliation label when one is known."""
    text = str(affiliation or "").strip()
    if not text:
        return text
    aliases = load_affiliation_display_aliases()
    if not aliases:
        return text
    if text in aliases:
        return aliases[text]
    base = affiliation_base_name(text)
    if base in aliases:
        return aliases[base]
    fingerprint = _affiliation_fingerprint(text)
    for key, value in aliases.items():
        if _affiliation_fingerprint(key) == fingerprint:
            return value
    return text


def affiliation_display_name(affiliation: str) -> str:
    """Human-readable affiliation label with accents and regional qualifiers."""
    affiliation = resolve_affiliation_alias(affiliation)
    text = _clean_affiliation_display(_strip_country_suffix_display(affiliation))
    if not text:
        return ""
    key = canonical_affiliation_key(affiliation)
    rule = _institution_rule(affiliation)
    if rule and rule.get("canonical"):
        canonical = str(rule["canonical"])
        if " / " in text and text.lower().startswith(canonical.lower()):
            return text
        if key == canonical:
            return canonical
        if key.startswith(f"{canonical} -"):
            return key
    return text


def _regionalized_canonical_name(
    affiliation: str, rule: dict[str, Any], base: str
) -> str:
    canonical = str(rule.get("canonical") or base or "").strip()
    if not canonical or not rule.get("regionalize"):
        return canonical or base
    regional_suffix_re = re.compile(
        f"^{re.escape(canonical)}\\s*[-–]\\s*(.+)$", re.IGNORECASE
    )
    match = regional_suffix_re.match(_clean_affiliation_display(base))
    if match:
        return f"{canonical} - {match.group(1).strip()}"
    regional_countries = rule.get("regional_countries") or {}
    for hint in _extract_country_hints(affiliation):
        label = regional_countries.get(hint)
        if label:
            return f"{canonical} - {label}"
    return canonical


def _affiliation_fingerprint(text: str) -> str:
    """Fold punctuation/Unicode variants for override and cache matching."""
    folded = unicodedata.normalize("NFKD", str(text or ""))
    for char in ("ʻ", "ʼ", "'", "'", "`", "´", "’", "ʻ"):
        folded = folded.replace(char, "")
    folded = folded.encode("ascii", "ignore").decode("ascii")
    folded = folded.replace("–", "-").replace("–", "-")
    for pattern, replacement in _NORMALIZATIONS:
        folded = re.sub(pattern, replacement, folded)
    return folded.strip(" ,;-").casefold()


def canonical_affiliation_key(affiliation: str) -> str:
    """Stable key for deduplicating institution variants."""
    affiliation = resolve_affiliation_alias(affiliation)
    base = _clean_affiliation_display(
        _strip_country_suffix_display(affiliation) or affiliation_base_name(affiliation)
    )
    for pattern, rule in _INSTITUTION_GEO_RULES:
        if pattern.search(affiliation):
            return _regionalized_canonical_name(affiliation, rule, base) or base
    return base or _normalize_text(affiliation).strip()


def affiliation_lookup_keys(affiliation: str) -> list[str]:
    """Candidate keys for overrides and cache propagation."""
    keys: list[str] = []
    seen: set[str] = set()

    def add(value: str | None) -> None:
        if not value:
            return
        cleaned = value.strip()
        if cleaned and cleaned not in seen:
            seen.add(cleaned)
            keys.append(cleaned)

    add(affiliation)
    add(_normalize_text(affiliation))
    add(affiliation_base_name(affiliation))
    for pattern, rule in _INSTITUTION_GEO_RULES:
        if pattern.search(affiliation):
            add(rule.get("canonical"))
    return keys


def _institution_rule(affiliation: str) -> dict[str, Any] | None:
    for pattern, rule in _INSTITUTION_GEO_RULES:
        if pattern.search(affiliation):
            return rule
    return None


def _filtered_country_hints(affiliation: str) -> list[str]:
    hints = _extract_country_hints(affiliation)
    rule = _institution_rule(affiliation)
    if not rule:
        return hints
    allowed = rule.get("countries") or []
    if not allowed:
        return hints
    filtered = [hint for hint in hints if hint in allowed]
    return filtered or list(allowed)


def _override_payload(override: dict[str, Any]) -> dict[str, float | str | None]:
    return {
        "latitude": override.get("latitude"),
        "longitude": override.get("longitude"),
        "query_used": override.get("query_used", "override"),
        "geocode_level": override.get("geocode_level", "institute"),
    }


def _lookup_override(
    affiliation: str, overrides: dict[str, dict]
) -> dict[str, float | str | None] | None:
    for key in affiliation_lookup_keys(affiliation):
        if key in overrides:
            return _override_payload(overrides[key])
    if not overrides:
        return None
    by_fingerprint = {
        _affiliation_fingerprint(key): key
        for key in overrides
        if _affiliation_fingerprint(key)
    }
    for key in affiliation_lookup_keys(affiliation):
        matched = by_fingerprint.get(_affiliation_fingerprint(key))
        if matched is not None:
            return _override_payload(overrides[matched])
    return None


def _split_primary_segment(affiliation: str) -> str:
    for sep in ("/", ";", "|"):
        if sep in affiliation:
            affiliation = affiliation.split(sep, 1)[0]
    return affiliation.strip()


def _lookup_country(name: str) -> str | None:
    cleaned = _normalize_text(name).strip(" ,.-")
    if not cleaned or len(cleaned) < 3:
        return None
    alias = _COUNTRY_ALIASES.get(cleaned.lower())
    if alias:
        return alias
    try:
        return pycountry.countries.lookup(cleaned).name
    except LookupError:
        return None


def _extract_country_hints(affiliation: str) -> list[str]:
    """Extract likely country/region names from an affiliation string."""
    hints: list[str] = []
    seen: set[str] = set()

    def add(candidate: str | None, *, resolved: bool = False) -> None:
        if not candidate:
            return
        country = candidate if resolved else _lookup_country(candidate)
        if country and country not in seen:
            seen.add(country)
            hints.append(country)

    normalized = _normalize_text(affiliation)
    lowered = normalized.lower()
    for alias, country in sorted(
        _COUNTRY_ALIASES.items(), key=lambda item: -len(item[0])
    ):
        if alias in lowered:
            add(country, resolved=True)
    for part in re.split("[,;/|&]", normalized):
        add(part.strip())
    for sep in (" - ", " – ", " – "):
        if sep in normalized:
            tail = normalized.split(sep, 1)[1]
            for part in re.split("[,;/|&]", tail):
                add(part.strip())
    return hints


def _query_variants(affiliation: str) -> list[str]:
    """Generate progressively simpler geocoding queries."""
    raw = affiliation.strip()
    if not raw:
        return []
    normalized = _normalize_text(raw)
    primary = _split_primary_segment(normalized)
    variants: list[str] = []
    seen: set[str] = set()

    def add(query: str | None) -> None:
        if not query:
            return
        query = _normalize_text(query)
        if query and query not in seen:
            seen.add(query)
            variants.append(query)

    rule = _institution_rule(raw)
    if rule and rule.get("query"):
        add(rule["query"])
    add(raw)
    add(normalized)
    add(primary)
    lowered = primary.lower()
    for fragment, alias in _AFFILIATION_ALIASES.items():
        if fragment in lowered:
            add(alias)
    country_hints = _filtered_country_hints(raw)
    base_name = affiliation_base_name(raw)
    for country in country_hints:
        add(f"{base_name or primary}, {country}")
        add(f"{primary}, {country}")
    if "(" in primary and ")" in primary:
        add(re.sub("\\([^)]*\\)", "", primary).strip(" ,"))
    parts = [part.strip() for part in re.split(",", primary) if part.strip()]
    if len(parts) >= 2:
        add(f"{parts[0]}, {parts[-1]}")
        add(f"{parts[0]} {parts[-1]}")
        add(parts[0])
        add(f"{parts[0]}, {parts[1]}")
        add(f"{parts[1]}, {parts[0]}")
    for sep in (" - ", " – ", " – "):
        if sep in primary:
            add(primary.split(sep, 1)[0])
    if " under " in lowered:
        add(primary.split(" under ", 1)[0])
    if "university" in lowered:
        match = re.search(
            "((?:the\\s+)?university of [^,;/|-]+)", primary, flags=re.IGNORECASE
        )
        if match:
            add(match.group(1))
            for country in country_hints:
                add(f"{match.group(1)}, {country}")
    if "institute" in lowered:
        match = re.search(
            "(institute[^,;/|]*?(?:,\\s*[^,;/|]+)?)", primary, flags=re.IGNORECASE
        )
        if match:
            add(match.group(1))
    if "antsiranana" in lowered:
        add("Universite d'Antsiranana, Madagascar")
    if "salento" in lowered:
        add("Universita del Salento, Lecce, Italy")
    if "toliara" in lowered:
        add("Universite de Toliara, Madagascar")
    if "mons" in lowered and "belgium" in lowered:
        add("Universite de Mons, Belgium")
    add(
        re.split(
            ",\\s*(?:Department|School|Faculty|Center|Centre|Division)\\b",
            primary,
            maxsplit=1,
        )[0]
    )
    return [
        query
        for query in variants
        if len(query) >= 12 or query.lower() in _AFFILIATION_ALIASES
    ]
