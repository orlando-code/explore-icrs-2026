"""Google Maps Geocoding API lookups with persistent caching."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlencode

import requests

from src.data_paths import GOOGLE_GEOCODE_CACHE_JSON
from src.geocoding.geocode import _normalize_text, _query_variants, canonical_affiliation_key
from src.util.json_io import load_json

DEFAULT_GOOGLE_CACHE_PATH = GOOGLE_GEOCODE_CACHE_JSON
DEFAULT_KEYS_PATH = Path("keys.yaml")
_GOOGLE_GEOCODE_URL = "https://maps.googleapis.com/maps/api/geocode/json"


def load_google_maps_api_key(keys_path: Path | str = DEFAULT_KEYS_PATH) -> str:
    path = Path(keys_path)
    if not path.exists():
        raise FileNotFoundError(f"Missing API keys file: {path}")
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if stripped.startswith("google_maps_api_key:"):
            key = stripped.split(":", 1)[1].strip().strip('"').strip("'")
            if key:
                return key
    raise ValueError(f"No google_maps_api_key found in {path}")


def _query_cache_key(query: str) -> str:
    return _normalize_text(query).lower()


def _load_google_cache(path: Path) -> dict[str, Any]:
    raw = load_json(path, default={})
    if not raw:
        return {"queries": {}, "affiliations": {}}
    if "queries" in raw and "affiliations" in raw:
        return raw
    return {"queries": raw if isinstance(raw, dict) else {}, "affiliations": {}}


def _save_google_cache(path: Path, cache: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(cache, handle, indent=2, sort_keys=True)


def _google_result_from_payload(query: str, payload: dict[str, Any]) -> dict[str, Any] | None:
    status = payload.get("status")
    if status == "ZERO_RESULTS":
        return None
    if status != "OK":
        raise RuntimeError(f"Google Geocoding API error for {query!r}: {status}")
    results = payload.get("results") or []
    if not results:
        return None
    top = results[0]
    location = top.get("geometry", {}).get("location") or {}
    lat = location.get("lat")
    lon = location.get("lng")
    if lat is None or lon is None:
        return None
    return {
        "latitude": float(lat),
        "longitude": float(lon),
        "formatted_address": top.get("formatted_address"),
        "place_id": top.get("place_id"),
        "query": query,
        "status": status,
    }


def _fetch_google_query(
    query: str,
    *,
    api_key: str,
    pause_seconds: float,
    api_calls: list[int] | None = None,
) -> dict[str, Any] | None:
    params = urlencode({"address": query, "key": api_key})
    response = requests.get(f"{_GOOGLE_GEOCODE_URL}?{params}", timeout=20)
    response.raise_for_status()
    payload = response.json()
    if api_calls is not None:
        api_calls.append(1)
    time.sleep(pause_seconds)
    return _google_result_from_payload(query, payload)


def _lookup_query_cache(cache: dict[str, Any], query: str) -> dict[str, Any] | None:
    entry = cache["queries"].get(_query_cache_key(query))
    if not entry or entry.get("latitude") is None:
        return None
    return dict(entry)


def _lookup_affiliation_cache(cache: dict[str, Any], affiliation: str) -> dict[str, Any] | None:
    canonical = canonical_affiliation_key(affiliation)
    entry = cache["affiliations"].get(canonical)
    if not entry or entry.get("latitude") is None:
        return None
    return dict(entry)


def google_geocode_affiliation(
    affiliation: str,
    *,
    api_key: str,
    google_cache: dict[str, Any],
    pause_seconds: float = 0.05,
    on_query: Callable[[str, int, int], None] | None = None,
    api_calls: list[int] | None = None,
) -> dict[str, Any] | None:
    """Resolve an affiliation via Google, using query + canonical affiliation caches."""
    cached = _lookup_affiliation_cache(google_cache, affiliation)
    if cached is not None:
        return cached
    canonical = canonical_affiliation_key(affiliation)
    variants = _query_variants(affiliation)
    total = len(variants)
    for index, query in enumerate(variants, start=1):
        if on_query is not None:
            on_query(query, index, total)
        cached_query = _lookup_query_cache(google_cache, query)
        if cached_query is not None:
            result = cached_query
        else:
            result = _fetch_google_query(
                query, api_key=api_key, pause_seconds=pause_seconds, api_calls=api_calls
            )
            google_cache["queries"][_query_cache_key(query)] = result or {
                "latitude": None,
                "longitude": None,
                "formatted_address": None,
                "place_id": None,
                "query": query,
                "status": "ZERO_RESULTS",
            }
        if result is None:
            continue
        enriched = {
            **result,
            "canonical_key": canonical,
            "query_used": f"google:{result.get('query') or query}",
            "geocode_level": "institute",
        }
        google_cache["affiliations"][canonical] = enriched
        return enriched
    return None
