"""Load country and US-state capital coordinates from data/geography/."""

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

from src.data_paths import GEOGRAPHY
from src.sources.delegates import country_to_iso2

COUNTRY_CAPITALS_JSON = GEOGRAPHY / "country_capitals.json"
US_STATE_CAPITALS_JSON = GEOGRAPHY / "us_state_capitals.json"


class CapitalCoordsError(LookupError):
    """Raised when a known country has no capital coordinates in the reference data."""


@dataclass(frozen=True, slots=True)
class CapitalRecord:
    city: str
    lat: float
    lon: float
    country: str = ""
    iso2: str = ""
    source: str = ""


def _load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(
            f"Missing capital reference data at {path}. "
            "Run: python scripts/pipeline/build_capital_coords_data.py"
        )
    return json.loads(path.read_text(encoding="utf-8"))


@lru_cache(maxsize=1)
def country_capital_index() -> dict[str, CapitalRecord]:
    payload = _load_json(COUNTRY_CAPITALS_JSON)
    index: dict[str, CapitalRecord] = {}
    for iso2, row in payload.get("countries", {}).items():
        iso = str(iso2 or "").strip().upper()
        if not iso:
            continue
        index[iso] = CapitalRecord(
            city=str(row.get("city") or "").strip(),
            lat=float(row["lat"]),
            lon=float(row["lon"]),
            country=str(row.get("country") or "").strip(),
            iso2=iso,
            source=str(row.get("source") or "country_capitals.json"),
        )
    return index


@lru_cache(maxsize=1)
def us_state_capital_index() -> tuple[dict[str, CapitalRecord], dict[str, str]]:
    payload = _load_json(US_STATE_CAPITALS_JSON)
    states: dict[str, CapitalRecord] = {}
    for name, row in payload.get("states", {}).items():
        state_name = str(name or "").strip()
        if not state_name:
            continue
        states[state_name] = CapitalRecord(
            city=str(row.get("city") or "").strip(),
            lat=float(row["lat"]),
            lon=float(row["lon"]),
            country="United States",
            source="us_state_capitals.json",
        )
    aliases = {
        str(alias).strip().casefold(): str(canonical).strip()
        for alias, canonical in payload.get("aliases", {}).items()
        if str(alias).strip() and str(canonical).strip()
    }
    return states, aliases


def clear_capital_data_cache() -> None:
    country_capital_index.cache_clear()
    us_state_capital_index.cache_clear()


def lookup_country_capital(
    country: str,
    *,
    require: bool = False,
) -> CapitalRecord | None:
    """Resolve a delegate country label to a capital record via ISO2."""
    cleaned = str(country or "").strip()
    if not cleaned:
        return None
    iso2 = country_to_iso2(cleaned)
    if not iso2:
        if require:
            raise CapitalCoordsError(f"Unknown country label {country!r}")
        return None
    record = country_capital_index().get(iso2)
    if record is None and require:
        raise CapitalCoordsError(
            f"No capital coordinates for {country!r} (ISO {iso2}). "
            "Add an entry to data/geography/country_capitals.json via "
            "scripts/pipeline/build_capital_coords_data.py."
        )
    return record


def lookup_us_state_capital(state_name: str) -> CapitalRecord | None:
    states, _aliases = us_state_capital_index()
    return states.get(state_name)


def us_state_aliases() -> dict[str, str]:
    _states, aliases = us_state_capital_index()
    return aliases


def us_state_names() -> frozenset[str]:
    states, _aliases = us_state_capital_index()
    return frozenset(states)


def countries_missing_capital_data(countries: list[str]) -> list[tuple[str, str]]:
    """Return (country label, iso2) pairs with no capital record."""
    missing: list[tuple[str, str]] = []
    for country in countries:
        cleaned = str(country or "").strip()
        if not cleaned:
            continue
        iso2 = country_to_iso2(cleaned)
        if not iso2:
            missing.append((cleaned, ""))
            continue
        if iso2 not in country_capital_index():
            missing.append((cleaned, iso2))
    return missing
