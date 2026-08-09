"""Capital-city coordinates for affiliation geocode fallbacks."""

from __future__ import annotations

import re
import unicodedata
from typing import Any

from src.geocoding.capital_data import (
    CapitalCoordsError,
    CapitalRecord,
    lookup_country_capital,
    lookup_us_state_capital,
    us_state_aliases,
    us_state_names,
)
from src.sources.delegates import COUNTRY_ALIASES, country_to_iso2

_AUSTRALIAN_STATE_NAMES = frozenset(
    {
        "western australia",
        "south australia",
        "new south wales",
        "queensland",
        "victoria",
        "tasmania",
        "northern territory",
        "australian capital territory",
    }
)

_US_STATE_PATTERN = re.compile(
    r"\b("
    + "|".join(
        re.escape(name)
        for name in sorted(us_state_names(), key=len, reverse=True)
        if name not in {"District of Columbia"}
    )
    + r")\b",
    re.IGNORECASE,
)


def _normalize_text(value: str) -> str:
    return unicodedata.normalize("NFKC", str(value or "")).strip()


def _canonical_country(country: str) -> str:
    cleaned = _normalize_text(country)
    if not cleaned:
        return ""
    alias = COUNTRY_ALIASES.get(cleaned.casefold())
    return alias or cleaned


def _detect_us_state(*texts: str) -> str | None:
    combined = " ".join(_normalize_text(text) for text in texts if text)
    if not combined:
        return None
    lowered = combined.casefold()
    for aus_state in _AUSTRALIAN_STATE_NAMES:
        if aus_state in lowered:
            return None
    for alias, state in us_state_aliases().items():
        if re.search(rf"\b{re.escape(alias)}\b", lowered):
            return state
    match = _US_STATE_PATTERN.search(combined)
    if not match:
        return None
    matched = match.group(1)
    for canonical in us_state_names():
        if canonical.casefold() == matched.casefold():
            return canonical
    return matched


_MAX_PLAUSIBLE_COUNTRY_DISTANCE_KM = 1_500


def _countries_implied_by_organisation(organisation: str) -> list[str]:
    from src.geocoding.geocode import (
        _COUNTRY_ALIASES,
        _extract_country_hints,
        _institution_rule,
        _normalize_text,
    )

    organisation = str(organisation or "").strip()
    if not organisation:
        return []

    implied = list(_extract_country_hints(organisation))
    rule = _institution_rule(organisation)
    if rule:
        for name in rule.get("countries") or []:
            if name not in implied:
                implied.append(str(name))

    lowered = _normalize_text(organisation).lower()
    for alias, country in sorted(_COUNTRY_ALIASES.items(), key=lambda item: -len(item[0])):
        if len(alias) < 4:
            continue
        if re.search(rf"\b{re.escape(alias)}\b", lowered) and country not in implied:
            implied.append(country)
    return implied


def _country_reference_point(country: str) -> tuple[float, float] | None:
    record = lookup_country_capital(country)
    if record is not None:
        return record.lat, record.lon
    canonical = _canonical_country(country)
    state_record = lookup_us_state_capital(canonical)
    if state_record is not None:
        return state_record.lat, state_record.lon
    return None


def coords_plausible_for_country(lat: float, lon: float, country: str) -> bool:
    """Rough check that coordinates lie near the delegate country (capital within ~1500 km)."""
    from src.geocoding.geocode import _haversine_km

    reference = _country_reference_point(country)
    if reference is None:
        return True
    ref_lat, ref_lon = reference
    return _haversine_km(lat, lon, ref_lat, ref_lon) <= _MAX_PLAUSIBLE_COUNTRY_DISTANCE_KM


def organisation_country_mismatch(organisation: str, country: str) -> bool:
    """True when the organisation name implies a home country different from delegate country."""
    from src.geocoding.geocode import _institution_rule

    organisation = str(organisation or "").strip()
    country = str(country or "").strip()
    if not organisation or not country:
        return False

    implied = _countries_implied_by_organisation(organisation)
    rule = _institution_rule(f"{organisation}, {country}")
    if rule and not rule.get("countries"):
        return False

    if not implied:
        return False

    stated_iso = country_to_iso2(country)
    stated_cf = country.casefold()
    for hint in implied:
        hint_iso = country_to_iso2(hint)
        if hint_iso and stated_iso and hint_iso == stated_iso:
            return False
        if hint.casefold() == stated_cf:
            return False
    return True


def _record_to_fallback(
    record: CapitalRecord,
    *,
    display_country: str,
    scope_label: str,
) -> tuple[str, float, float, str]:
    return (
        record.city,
        record.lat,
        record.lon,
        f"fallback:capital:{record.city}, {scope_label}",
    )


def resolve_capital_fallback(
    organisation: str,
    country: str,
    *,
    require: bool = False,
) -> tuple[str, float, float, str] | None:
    """Return (city, lat, lon, query_label) for a capital fallback, or None."""
    country_name = str(country or "").strip()
    if not country_name:
        return None

    canonical_country = _canonical_country(country_name)
    iso2 = country_to_iso2(canonical_country) or country_to_iso2(country_name)
    if not iso2:
        if require:
            raise CapitalCoordsError(f"Unknown country label {country_name!r}")
        return None

    if canonical_country == "United States" or iso2 == "US":
        state = _detect_us_state(organisation, country_name)
        if state:
            state_record = lookup_us_state_capital(state)
            if state_record is not None:
                return _record_to_fallback(
                    state_record,
                    display_country=f"{state}, United States",
                    scope_label=f"{state}, United States",
                )
            if require:
                raise CapitalCoordsError(
                    f"No US state capital coordinates for {state!r} in us_state_capitals.json"
                )
        us_record = lookup_country_capital("United States", require=require)
        if us_record is not None:
            return _record_to_fallback(
                us_record,
                display_country="United States",
                scope_label="United States",
            )
        return None

    state_record = lookup_us_state_capital(canonical_country)
    if state_record is not None:
        return _record_to_fallback(
            state_record,
            display_country=canonical_country,
            scope_label=canonical_country,
        )

    record = lookup_country_capital(country_name, require=require)
    if record is None:
        return None
    display_country = record.country or canonical_country or country_name
    return _record_to_fallback(
        record,
        display_country=display_country,
        scope_label=display_country,
    )


def resolve_country_anchor_fallback(
    organisation: str,
    country: str,
    *,
    require: bool = False,
) -> tuple[str, float, float, str] | None:
    """Capital of delegate country when the org name points elsewhere."""
    if not organisation_country_mismatch(organisation, country):
        return None
    return resolve_capital_fallback(organisation, country, require=require)


def capital_geocode_hit(
    organisation: str,
    country: str,
    *,
    require: bool = False,
) -> dict[str, Any] | None:
    """Return a geocode-style dict from country/state capital fallback."""
    country_name = str(country or "").strip()
    if not country_name:
        return None
    fallback = resolve_capital_fallback(organisation, country_name, require=require)
    if fallback is None:
        return None
    city, lat, lon, query_label = fallback
    return {
        "latitude": lat,
        "longitude": lon,
        "formatted_address": f"{city}, {country_name}",
        "query_used": query_label,
        "geocode_level": "country",
        "geocoded": True,
        "country": country_name,
    }


__all__ = [
    "CapitalCoordsError",
    "capital_geocode_hit",
    "coords_plausible_for_country",
    "organisation_country_mismatch",
    "resolve_capital_fallback",
    "resolve_country_anchor_fallback",
]
