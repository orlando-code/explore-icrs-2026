"""ISO-3166 alpha-2 land-border adjacency for country clustering."""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

from src.geography.country_continents import continent_for_country, load_country_continents
from src.data_paths import COUNTRY_BOUNDARIES_CENTROIDS_JSON, COUNTRY_NEIGHBOURS_JSON
from src.util.geo_math import haversine_km as _haversine_km

NEIGHBOURS_PATH = COUNTRY_NEIGHBOURS_JSON
CENTROIDS_PATH = COUNTRY_BOUNDARIES_CENTROIDS_JSON

# Applied even when a generated adjacency file exists.
NEIGHBOUR_OVERRIDES: dict[str, list[str]] = {
    "AE": ["OM", "QA", "SA"],
    "BH": ["QA", "SA"],
    "GI": ["ES"],
    "HK": ["CN"],
    "KW": ["IQ", "SA"],
    "MC": ["FR"],
    "MO": ["CN"],
    "OM": ["AE", "SA", "YE"],
    "PS": ["EG", "IL", "JO"],
    "QA": ["SA"],
    "RE": ["MG", "YT"],
    "SG": ["MY"],
    "SX": ["CW", "GP", "MQ", "AG", "KN", "DO"],
    "SM": ["IT"],
    "VA": ["IT"],
    "YT": ["MG", "RE"],
}

PROXIMITY_MAX_KM = 1_350
PROXIMITY_MAX_NEIGHBOURS = 6

# Prefer attaching microstates to a nearby mainland country (not overseas territories).
HOST_PREFERENCES: dict[str, str] = {
    "HK": "CN",
    "MO": "CN",
    "GI": "ES",
    "SM": "IT",
    "SX": "CW",
    "VA": "IT",
}


def _proximity_neighbours(
  centroids: dict[str, tuple[float, float]],
  continents: dict[str, str],
) -> dict[str, list[str]]:
    neighbours: dict[str, set[str]] = {code: set() for code in centroids}
    for code, (lat, lon) in centroids.items():
        continent = continent_for_country(code, continents)
        if not continent:
            continue
        ranked: list[tuple[float, str]] = []
        for other, (other_lat, other_lon) in centroids.items():
            if other == code:
                continue
            if continent_for_country(other, continents) != continent:
                continue
            ranked.append((_haversine_km(lat, lon, other_lat, other_lon), other))
        ranked.sort()
        for distance, other in ranked[:PROXIMITY_MAX_NEIGHBOURS]:
            if distance > PROXIMITY_MAX_KM:
                break
            neighbours[code].add(other)
            neighbours[other].add(code)
    return {code: sorted(values) for code, values in neighbours.items()}


def _load_centroids() -> dict[str, tuple[float, float]]:
    if not CENTROIDS_PATH.exists():
        return {}
    payload = json.loads(CENTROIDS_PATH.read_text(encoding="utf-8"))
    return {
        str(code).upper(): (float(value[0]), float(value[1]))
        for code, value in payload.items()
        if isinstance(value, (list, tuple)) and len(value) >= 2
    }


@lru_cache(maxsize=1)
def load_country_neighbours() -> dict[str, list[str]]:
    mapping: dict[str, set[str]] = {}
    if NEIGHBOURS_PATH.exists():
        payload = json.loads(NEIGHBOURS_PATH.read_text(encoding="utf-8"))
        for code, neighbours in payload.items():
            iso2 = str(code).strip().upper()
            if not iso2:
                continue
            mapping.setdefault(iso2, set()).update(
                str(neighbour).strip().upper()
                for neighbour in neighbours
                if str(neighbour).strip()
            )

    centroids = _load_centroids()
    if centroids:
        for code, neighbours in _proximity_neighbours(centroids, load_country_continents()).items():
            mapping.setdefault(code, set()).update(neighbours)

    for code, neighbours in NEIGHBOUR_OVERRIDES.items():
        iso2 = str(code).strip().upper()
        bucket = mapping.setdefault(iso2, set())
        for neighbour in neighbours:
            neighbour_code = str(neighbour).strip().upper()
            if not neighbour_code:
                continue
            bucket.add(neighbour_code)
            mapping.setdefault(neighbour_code, set()).add(iso2)

    return {code: sorted(neighbours) for code, neighbours in mapping.items()}


def neighbours_for_country(code: str, neighbours: dict[str, list[str]] | None = None) -> list[str]:
    mapping = neighbours or load_country_neighbours()
    return list(mapping.get(str(code or "").strip().upper(), []))
