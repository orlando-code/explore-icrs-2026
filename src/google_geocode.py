"""Google Maps Geocoding API supplement with persistent caching."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Callable, Iterable
from urllib.parse import urlencode

import requests
from rich.console import Console
from rich.table import Table

from src.geocode import (
    DEFAULT_CACHE_PATH,
    DEFAULT_OVERRIDES_PATH,
    _haversine_km,
    _load_json,
    _lookup_override,
    _normalize_text,
    _propagate_canonical_geocodes,
    _query_variants,
    _save_cache,
    affiliation_lookup_keys,
    canonical_affiliation_key,
)

DEFAULT_GOOGLE_CACHE_PATH = Path("data/google_geocode_cache.json")
DEFAULT_GOOGLE_FLAGS_PATH = Path("data/google_geocode_flags.json")
DEFAULT_KEYS_PATH = Path("keys.yaml")
DISTANCE_FLAG_KM = 10.0
_GOOGLE_GEOCODE_URL = "https://maps.googleapis.com/maps/api/geocode/json"
_CONSOLE = Console()


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
    raw = _load_json(path)
    if not raw:
        return {"queries": {}, "affiliations": {}}
    if "queries" in raw and "affiliations" in raw:
        return raw
    # Legacy / empty shape.
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
    if not entry:
        return None
    if entry.get("latitude") is None:
        return None
    return dict(entry)


def _lookup_affiliation_cache(
    cache: dict[str, Any], affiliation: str
) -> dict[str, Any] | None:
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
                query,
                api_key=api_key,
                pause_seconds=pause_seconds,
                api_calls=api_calls,
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


def _effective_coords(
    affiliation: str,
    geocode_cache: dict[str, dict],
    overrides: dict[str, dict],
) -> tuple[float, float, str] | None:
    override = _lookup_override(affiliation, overrides)
    if override is not None and override.get("latitude") is not None:
        return (
            float(override["latitude"]),
            float(override["longitude"]),
            "override",
        )

    cached = geocode_cache.get(affiliation)
    if cached and cached.get("latitude") is not None:
        return (
            float(cached["latitude"]),
            float(cached["longitude"]),
            "cache",
        )

    for key in affiliation_lookup_keys(affiliation):
        cached = geocode_cache.get(key)
        if cached and cached.get("latitude") is not None:
            return (
                float(cached["latitude"]),
                float(cached["longitude"]),
                "cache",
            )

    return None


def _group_affiliations(affiliations: Iterable[str]) -> dict[str, list[str]]:
    groups: dict[str, list[str]] = {}
    for affiliation in affiliations:
        cleaned = (affiliation or "").strip()
        if not cleaned:
            continue
        key = canonical_affiliation_key(cleaned)
        groups.setdefault(key, [])
        if cleaned not in groups[key]:
            groups[key].append(cleaned)
    return groups


def _apply_google_coords(
    affiliation: str,
    google: dict[str, Any],
    *,
    geocode_cache: dict[str, dict],
    overrides: dict[str, dict],
) -> None:
    coords = {
        "latitude": google["latitude"],
        "longitude": google["longitude"],
        "query_used": google.get("query_used")
        or f"google:{google.get('formatted_address') or google.get('query')}",
        "geocode_level": google.get("geocode_level", "institute"),
        "google_formatted_address": google.get("formatted_address"),
        "google_place_id": google.get("place_id"),
    }

    geocode_cache[affiliation] = dict(coords)

    for key in affiliation_lookup_keys(affiliation):
        if key in overrides:
            overrides[key] = {
                **overrides[key],
                **coords,
                "query_used": coords["query_used"],
            }


def _save_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, sort_keys=True)


def _print_flags(flags: list[dict[str, Any]]) -> None:
    if not flags:
        _CONSOLE.print("[green]No Google geocode discrepancies over "
                       f"{DISTANCE_FLAG_KM:g} km.[/]")
        return

    table = Table(title=f"Google geocode flags (>{DISTANCE_FLAG_KM:g} km)")
    table.add_column("Affiliation", overflow="fold", max_width=42)
    table.add_column("Distance (km)", justify="right")
    table.add_column("Previous", overflow="fold", max_width=28)
    table.add_column("Google address", overflow="fold", max_width=36)
    table.add_column("Google coords", overflow="fold", max_width=22)

    for flag in sorted(flags, key=lambda item: -item["distance_km"]):
        prev = flag["previous_coords"]
        google = flag["google_coords"]
        table.add_row(
            flag["affiliation"],
            f"{flag['distance_km']:.1f}",
            f"{prev['lat']:.5f}, {prev['lon']:.5f} ({flag['previous_source']})",
            flag.get("google_formatted_address") or "",
            f"{google['lat']:.5f}, {google['lon']:.5f}",
        )

    _CONSOLE.print(table)


def supplement_with_google_geocodes(
    affiliations: Iterable[str],
    *,
    api_key: str | None = None,
    keys_path: Path | str = DEFAULT_KEYS_PATH,
    geocode_cache_path: Path | str = DEFAULT_CACHE_PATH,
    overrides_path: Path | str = DEFAULT_OVERRIDES_PATH,
    google_cache_path: Path | str = DEFAULT_GOOGLE_CACHE_PATH,
    flags_path: Path | str = DEFAULT_GOOGLE_FLAGS_PATH,
    distance_flag_km: float = DISTANCE_FLAG_KM,
    pause_seconds: float = 0.05,
    show_progress: bool = True,
    dry_run: bool = False,
) -> list[dict[str, Any]]:
    """Compare Google geocodes to current coords; flag large shifts and apply Google."""
    resolved_api_key = api_key or load_google_maps_api_key(keys_path)

    geocode_cache_path = Path(geocode_cache_path)
    overrides_path = Path(overrides_path)
    google_cache_path = Path(google_cache_path)
    flags_path = Path(flags_path)

    geocode_cache = _load_json(geocode_cache_path)
    overrides = _load_json(overrides_path)
    google_cache = _load_google_cache(google_cache_path)

    groups = _group_affiliations(affiliations)
    flags: list[dict[str, Any]] = []
    api_calls: list[int] = []
    affiliation_cache_hits = 0
    applied = 0
    failed = 0

    if show_progress:
        _CONSOLE.print(
            f"[bold]Google geocode supplement[/] "
            f"({len(groups)} canonical affiliations, cache: {google_cache_path})"
        )

    for canonical, members in sorted(groups.items(), key=lambda item: item[0].lower()):
        representative = max(members, key=len)
        baseline = _effective_coords(representative, geocode_cache, overrides)

        before_affiliation_cache = _lookup_affiliation_cache(google_cache, representative)
        if before_affiliation_cache is not None:
            affiliation_cache_hits += 1

        def on_query(query: str, attempt: int, total: int) -> None:
            if not show_progress:
                return
            label = representative if len(representative) <= 42 else f"{representative[:39]}..."
            _CONSOLE.print(
                f"[cyan]{label}[/] ({attempt}/{total}) {query[:72]}"
            )

        try:
            google = google_geocode_affiliation(
                representative,
                api_key=resolved_api_key,
                google_cache=google_cache,
                pause_seconds=pause_seconds,
                on_query=on_query,
                api_calls=api_calls,
            )
        except Exception as error:
            failed += 1
            if show_progress:
                _CONSOLE.print(f"[red]Failed[/] {representative}: {error}")
            continue

        if google is None:
            failed += 1
            if show_progress:
                _CONSOLE.print(f"[yellow]No Google result[/] {representative}")
            continue

        if not dry_run:
            _save_google_cache(google_cache_path, google_cache)

        distance_km = None
        if baseline is not None:
            distance_km = _haversine_km(
                baseline[0],
                baseline[1],
                google["latitude"],
                google["longitude"],
            )
            if distance_km > distance_flag_km:
                flags.append(
                    {
                        "canonical_key": canonical,
                        "affiliation": representative,
                        "affiliation_variants": members,
                        "distance_km": round(distance_km, 2),
                        "previous_source": baseline[2],
                        "previous_coords": {
                            "lat": baseline[0],
                            "lon": baseline[1],
                        },
                        "google_coords": {
                            "lat": google["latitude"],
                            "lon": google["longitude"],
                        },
                        "google_formatted_address": google.get("formatted_address"),
                        "google_place_id": google.get("place_id"),
                        "google_query": google.get("query"),
                    }
                )

        if dry_run:
            continue

        for member in members:
            _apply_google_coords(
                member,
                google,
                geocode_cache=geocode_cache,
                overrides=overrides,
            )
        applied += 1

        _propagate_canonical_geocodes(geocode_cache)
        _save_cache(geocode_cache_path, geocode_cache)
        _save_json(overrides_path, overrides)

    if not dry_run:
        _save_google_cache(google_cache_path, google_cache)
        _save_json(flags_path, flags)

    if show_progress:
        _CONSOLE.print(
            f"[green]Done.[/] Applied {applied:,} | Failed {failed:,} | "
            f"Google API calls {len(api_calls):,} | "
            f"Affiliation cache hits {affiliation_cache_hits:,} | "
            f"Flags {len(flags):,}"
        )
        _print_flags(flags)
        if flags and not dry_run:
            _CONSOLE.print(f"[bold]Review saved to[/] {flags_path}")

    return flags
