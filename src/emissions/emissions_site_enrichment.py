"""Enrich emissions site pools with country clusters for the offset choropleth."""

from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path
from typing import Any

from src.geography.country_clusters import build_country_clusters
from src.emissions.origin_country import (
    country_from_affiliation,
    country_label,
    iso3_from_iso2,
    resolve_origin_country,
)
from src.geography.territory_overlays import territory_overlay_codes
from src.emissions.travel_emissions import DEFAULT_REVERSE_CACHE_PATH
from src.data_paths import (
    COUNTRY_BOUNDARIES_REL,
    COUNTRY_BOUNDARIES_CENTROIDS_JSON,
    DELEGATES_JSON,
)

CENTROIDS_PATH = COUNTRY_BOUNDARIES_CENTROIDS_JSON
DELEGATES_PATH = DELEGATES_JSON


def _normalize_person_name(name: str) -> str:
    text = str(name or "").strip().casefold()
    for prefix in ("dr ", "prof ", "professor ", "mr ", "mrs ", "ms ", "miss "):
        if text.startswith(prefix):
            text = text[len(prefix) :].strip()
    return text


def _load_json(path: Path) -> dict:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def delegate_lookup() -> tuple[dict[str, str], dict[str, str]]:
    payload = _load_json(DELEGATES_PATH)
    by_name: dict[str, str] = {}
    by_name_code: dict[str, str] = {}
    for row in payload.get("delegates") or []:
        country = str(row.get("country") or "").strip()
        country_code = str(row.get("country_code") or "").strip().upper()
        keys = {
            str(row.get("full_name") or "").strip().casefold(),
            str(row.get("norm_name") or "").strip().casefold(),
            _normalize_person_name(row.get("full_name") or ""),
            _normalize_person_name(row.get("norm_name") or ""),
        }
        for key in keys:
            if not key:
                continue
            if country:
                by_name[key] = country
            if country_code:
                by_name_code[key] = country_code
    return by_name, by_name_code


def _delegate_for_attendee(
    name: str,
    delegate_countries: dict[str, str],
    delegate_country_codes: dict[str, str],
) -> tuple[str, str]:
    keys = [str(name or "").strip().casefold(), _normalize_person_name(name)]
    country = ""
    country_code = ""
    for key in keys:
        if not key:
            continue
        country = country or delegate_countries.get(key, "")
        country_code = country_code or delegate_country_codes.get(key, "")
    return country, country_code


def _location_index(pool: dict) -> dict[str, dict]:
    return {
        str(location.get("id")): location
        for location in pool.get("locations", [])
        if location.get("id")
    }


def _roster_country_counts(*, speakers_only: bool) -> dict[str, int]:
    payload = _load_json(DELEGATES_PATH)
    counts: dict[str, int] = defaultdict(int)
    for row in payload.get("delegates") or []:
        if speakers_only and not row.get("is_speaker"):
            continue
        code = str(row.get("country_code") or "").strip().upper()
        if len(code) == 2:
            counts[code] += 1
    return dict(counts)


def _country_counts_for_pool(
    pool: dict,
    *,
    reverse_cache: dict[str, dict[str, str]],
    delegate_countries: dict[str, str],
    delegate_country_codes: dict[str, str],
    speakers_only: bool,
) -> dict[str, int]:
    counts: dict[str, int] = defaultdict(int)
    locations = _location_index(pool)

    for location in pool.get("locations") or []:
        affiliation = str(location.get("affiliation") or "")
        code = resolve_origin_country(
            affiliation=affiliation,
            lat=location.get("lat"),
            lon=location.get("lon"),
            reverse_cache=reverse_cache,
            existing=str(location.get("origin_country") or ""),
        )
        if not code:
            code = country_from_affiliation(affiliation)
        if not code:
            continue
        attendees = int(location.get("travel_attendees") or 0) or 1
        counts[code] += attendees

    for attendee in pool.get("attendees") or []:
        location = locations.get(str(attendee.get("location_id") or ""), {})
        delegate_country, delegate_country_code = _delegate_for_attendee(
            str(attendee.get("name") or ""),
            delegate_countries,
            delegate_country_codes,
        )
        code = resolve_origin_country(
            affiliation=str(attendee.get("affiliation") or location.get("affiliation") or ""),
            lat=location.get("lat"),
            lon=location.get("lon"),
            reverse_cache=reverse_cache,
            delegate_country=delegate_country,
            delegate_country_code=delegate_country_code,
            existing=str(attendee.get("origin_country") or ""),
        )
        if code:
            counts[code] += 1

    for code, roster_total in _roster_country_counts(speakers_only=speakers_only).items():
        counts[code] = max(counts.get(code, 0), roster_total)

    return dict(counts)


def enrich_emissions_pool(
    pool: dict,
    *,
    reverse_cache: dict[str, dict[str, str]] | None = None,
    centroids: dict[str, tuple[float, float]] | None = None,
    delegate_countries: dict[str, str] | None = None,
    delegate_country_codes: dict[str, str] | None = None,
    speakers_only: bool = True,
) -> dict:
    reverse_cache = reverse_cache if reverse_cache is not None else _load_json(DEFAULT_REVERSE_CACHE_PATH)
    centroids = centroids if centroids is not None else centroids_from_json(CENTROIDS_PATH)
    if delegate_countries is None or delegate_country_codes is None:
        by_name, by_code = delegate_lookup()
        delegate_countries = delegate_countries or by_name
        delegate_country_codes = delegate_country_codes or by_code

    locations = _location_index(pool)
    country_counts = _country_counts_for_pool(
        pool,
        reverse_cache=reverse_cache,
        delegate_countries=delegate_countries,
        delegate_country_codes=delegate_country_codes,
        speakers_only=speakers_only,
    )
    country_labels = {code: country_label(code) for code in country_counts}
    clusters, country_to_cluster = build_country_clusters(
        country_counts,
        centroids,
        country_labels=country_labels,
    )
    cluster_labels = {
        cluster["cluster_id"]: cluster.get("label") or ", ".join(cluster.get("countries") or [])
        for cluster in clusters
    }

    attendees = []
    for attendee in pool.get("attendees") or []:
        location = locations.get(str(attendee.get("location_id") or ""), {})
        delegate_country, delegate_country_code = _delegate_for_attendee(
            str(attendee.get("name") or ""),
            delegate_countries,
            delegate_country_codes,
        )
        origin_country = resolve_origin_country(
            affiliation=str(attendee.get("affiliation") or location.get("affiliation") or ""),
            lat=location.get("lat"),
            lon=location.get("lon"),
            reverse_cache=reverse_cache,
            delegate_country=delegate_country,
            delegate_country_code=delegate_country_code,
            existing=str(attendee.get("origin_country") or ""),
        )
        attendees.append(
            {
                **attendee,
                "origin_country": origin_country,
                "country_cluster_id": country_to_cluster.get(origin_country, ""),
            }
        )

    enriched_locations = []
    for location in pool.get("locations") or []:
        affiliation = str(location.get("affiliation") or "")
        origin_country = resolve_origin_country(
            affiliation=affiliation,
            lat=location.get("lat"),
            lon=location.get("lon"),
            reverse_cache=reverse_cache,
            existing=str(location.get("origin_country") or ""),
        )
        if not origin_country:
            origin_country = country_from_affiliation(affiliation)
        enriched_locations.append(
            {
                **location,
                "origin_country": origin_country,
                "country_cluster_id": country_to_cluster.get(origin_country, ""),
            }
        )

    country_iso3_to_cluster = {
        iso3: cluster_id
        for code, cluster_id in country_to_cluster.items()
        if (iso3 := iso3_from_iso2(code))
    }

    return {
        **pool,
        "locations": enriched_locations,
        "attendees": attendees,
        "country_clusters": clusters,
        "country_to_cluster": country_to_cluster,
        "country_iso3_to_cluster": country_iso3_to_cluster,
        "country_cluster_labels": cluster_labels,
    }


def centroids_from_json(path: Path) -> dict[str, tuple[float, float]]:
    payload = _load_json(path)
    return {
        str(code).upper(): (float(value[0]), float(value[1]))
        for code, value in payload.items()
        if isinstance(value, (list, tuple)) and len(value) >= 2
    }


def enrich_emissions_payload(payload: dict[str, Any]) -> dict[str, Any]:
    reverse_cache = _load_json(DEFAULT_REVERSE_CACHE_PATH)
    centroids = centroids_from_json(CENTROIDS_PATH)
    delegate_countries, delegate_country_codes = delegate_lookup()

    for pool_name in ("speakers", "all_delegates"):
        pool = payload.get(pool_name)
        if pool:
            payload[pool_name] = enrich_emissions_pool(
                pool,
                reverse_cache=reverse_cache,
                centroids=centroids,
                delegate_countries=delegate_countries,
                delegate_country_codes=delegate_country_codes,
                speakers_only=pool_name == "speakers",
            )

    active_countries: set[str] = set()
    for pool_name in ("speakers", "all_delegates"):
        pool = payload.get(pool_name) or {}
        active_countries.update(pool.get("country_to_cluster", {}).keys())

    payload.setdefault("meta", {})
    payload["meta"]["offset_choropleth"] = {
        "enabled": True,
        "boundaries_path": COUNTRY_BOUNDARIES_REL,
        "min_cluster_size": 3,
        "color_low": "#d95f02",
        "color_high": "#2d8a4e",
        "boundaries_source": "maplibre-demotiles",
        "territory_overlay_iso2": territory_overlay_codes(active_countries),
    }
    return payload
