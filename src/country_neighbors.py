"""ISO-3166 alpha-2 land-border adjacency for country clustering."""

from __future__ import annotations

import json
import math
from functools import lru_cache
from pathlib import Path

from src.country_continents import continent_for_country, load_country_continents

PROJECT_ROOT = Path(__file__).resolve().parents[1]
NEIGHBORS_PATH = PROJECT_ROOT / "data" / "country_neighbors.json"
CENTROIDS_PATH = PROJECT_ROOT / "data" / "country_boundaries_centroids.json"

# Applied even when a generated adjacency file exists.
NEIGHBOR_OVERRIDES: dict[str, list[str]] = {
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
    "SM": ["IT"],
    "VA": ["IT"],
    "YT": ["MG", "RE"],
}

PROXIMITY_MAX_KM = 1_350
PROXIMITY_MAX_NEIGHBORS = 6

# Prefer attaching microstates to a nearby mainland country (not overseas territories).
HOST_PREFERENCES: dict[str, str] = {
    "HK": "CN",
    "MO": "CN",
    "GI": "ES",
    "SM": "IT",
    "VA": "IT",
}


def _haversine_km(
    lat1: float,
    lon1: float,
    lat2: float,
    lon2: float,
) -> float:
    radius_km = 6371.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    d_phi = math.radians(lat2 - lat1)
    d_lambda = math.radians(lon2 - lon1)
    a = (
        math.sin(d_phi / 2) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(d_lambda / 2) ** 2
    )
    return 2 * radius_km * math.asin(math.sqrt(a))


def _proximity_neighbors(
  centroids: dict[str, tuple[float, float]],
  continents: dict[str, str],
) -> dict[str, list[str]]:
    neighbors: dict[str, set[str]] = {code: set() for code in centroids}
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
        for distance, other in ranked[:PROXIMITY_MAX_NEIGHBORS]:
            if distance > PROXIMITY_MAX_KM:
                break
            neighbors[code].add(other)
            neighbors[other].add(code)
    return {code: sorted(values) for code, values in neighbors.items()}


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
def load_country_neighbors() -> dict[str, list[str]]:
    mapping: dict[str, set[str]] = {}
    if NEIGHBORS_PATH.exists():
        payload = json.loads(NEIGHBORS_PATH.read_text(encoding="utf-8"))
        for code, neighbors in payload.items():
            iso2 = str(code).strip().upper()
            if not iso2:
                continue
            mapping.setdefault(iso2, set()).update(
                str(neighbor).strip().upper()
                for neighbor in neighbors
                if str(neighbor).strip()
            )

    centroids = _load_centroids()
    if centroids:
        for code, neighbors in _proximity_neighbors(centroids, load_country_continents()).items():
            mapping.setdefault(code, set()).update(neighbors)

    for code, neighbors in NEIGHBOR_OVERRIDES.items():
        iso2 = str(code).strip().upper()
        bucket = mapping.setdefault(iso2, set())
        for neighbor in neighbors:
            neighbor_code = str(neighbor).strip().upper()
            if not neighbor_code:
                continue
            bucket.add(neighbor_code)
            mapping.setdefault(neighbor_code, set()).add(iso2)

    return {code: sorted(neighbors) for code, neighbors in mapping.items()}


def neighbors_for_country(code: str, neighbors: dict[str, list[str]] | None = None) -> list[str]:
    mapping = neighbors or load_country_neighbors()
    return list(mapping.get(str(code or "").strip().upper(), []))
