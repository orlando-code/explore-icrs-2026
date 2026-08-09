"""Resolve ISO-2 origin countries for emissions attendees and locations."""

from __future__ import annotations

from pathlib import Path

import pycountry

from src.emissions.travel_emissions import _country_name_to_alpha2
from src.geocoding.geocode import _extract_country_hints


def _load_reverse_cache(path: Path) -> dict[str, dict[str, str]]:
    if not path.exists():
        return {}
    import json

    return json.loads(path.read_text(encoding="utf-8"))


def country_from_coordinates(
    lat: float | None,
    lon: float | None,
    reverse_cache: dict[str, dict[str, str]],
) -> str:
    if lat is None or lon is None:
        return ""
    key = f"{float(lat):.4f},{float(lon):.4f}"
    geo = reverse_cache.get(key) or {}
    return str(geo.get("country_code") or "").strip().upper()


def country_from_affiliation(affiliation: str) -> str:
    text = str(affiliation or "").strip()
    if not text:
        return ""
    hints = _extract_country_hints(text)
    if hints:
        code = _country_name_to_alpha2(hints[0])
        if code:
            return code.upper()
    parts = [part.strip() for part in text.split(",") if part.strip()]
    if parts:
        code = _country_name_to_alpha2(parts[-1])
        if code:
            return code.upper()
    return ""


def resolve_origin_country(
    *,
    affiliation: str = "",
    lat: float | None = None,
    lon: float | None = None,
    reverse_cache: dict[str, dict[str, str]] | None = None,
    delegate_country: str = "",
    delegate_country_code: str = "",
    existing: str = "",
) -> str:
    delegate_code = str(delegate_country_code or "").strip().upper()
    if len(delegate_code) == 2 and delegate_code.isalpha():
        return delegate_code
    code = str(existing or "").strip().upper()
    if code and code not in {"UNKNOWN", "NAN"}:
        return code
    code = country_from_coordinates(lat, lon, reverse_cache or {})
    if code:
        return code
    code = country_from_affiliation(affiliation)
    if code:
        return code
    code = country_from_affiliation(delegate_country)
    if code:
        return code
    delegate_text = str(delegate_country or "").strip()
    if len(delegate_text) == 2 and delegate_text.isalpha():
        return delegate_text.upper()
    return ""


def iso3_from_iso2(code: str) -> str:
    text = str(code or "").strip().upper()
    if not text:
        return ""
    try:
        return pycountry.countries.get(alpha_2=text).alpha_3
    except (AttributeError, LookupError):
        return ""


def country_label(code: str) -> str:
    text = str(code or "").strip().upper()
    if not text:
        return ""
    try:
        return pycountry.countries.get(alpha_2=text).name
    except (AttributeError, LookupError):
        return text
