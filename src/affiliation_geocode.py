"""Simple Google-only affiliation geocoding (no Nominatim / legacy caches)."""

from __future__ import annotations

import math
import time
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlencode

import pandas as pd
import requests
from rich.console import Console
from rich.progress import BarColumn, Progress, TaskProgressColumn, TextColumn, TimeElapsedColumn

from src.delegates import (
    load_delegates,
    normalize_person_name,
)
from src.google_geocode import load_google_maps_api_key
from src.programme import load_talks

_GOOGLE_GEOCODE_URL = "https://maps.googleapis.com/maps/api/geocode/json"
_CONSOLE = Console()


@dataclass(frozen=True)
class AffiliationTarget:
    organisation: str
    country: str
    affiliation: str

    @property
    def key(self) -> tuple[str, str]:
        return (self.organisation.casefold(), self.country.casefold())

    def geocode_query(self) -> str:
        if self.country:
            return f"{self.organisation}, {self.country}"
        return self.organisation


_VAGUE_GEOCODE_TYPES = frozenset(
    {
        "country",
        "continent",
        "political",
        "administrative_area_level_1",
        "administrative_area_level_2",
    }
)
_PRECISE_GEOCODE_TYPES = frozenset(
    {
        "street_address",
        "route",
        "establishment",
        "point_of_interest",
        "university",
        "school",
        "premise",
        "subpremise",
        "locality",
        "postal_code",
        "neighborhood",
        "sublocality",
        "natural_feature",
    }
)


def _google_result_is_precise(result: dict[str, Any]) -> bool:
    types = set(result.get("types") or [])
    if types & _PRECISE_GEOCODE_TYPES:
        return True
    if types and types <= _VAGUE_GEOCODE_TYPES:
        return False
    location_type = (result.get("geometry") or {}).get("location_type")
    return location_type in {"ROOFTOP", "RANGE_INTERPOLATED", "GEOMETRIC_CENTER"}


def collect_affiliation_targets() -> list[AffiliationTarget]:
    """Gather unique organisation + country pairs from talks and delegates."""
    delegates = load_delegates(refresh=False)
    delegate_by_name: dict[str, tuple[str, str]] = {}
    for _, row in delegates.iterrows():
        organisation = str(row.get("organisation") or "").strip()
        country = str(row.get("country") or "").strip()
        if not organisation:
            continue
        for name_key in {
            normalize_person_name(str(row.get("full_name") or "")),
            str(row.get("full_name") or "").strip().casefold(),
        }:
            if name_key:
                delegate_by_name[name_key] = (organisation, country)

    targets: dict[tuple[str, str], AffiliationTarget] = {}

    def add(organisation: str, country: str, _affiliation: str = "") -> None:
        organisation = organisation.strip()
        country = country.strip()
        affiliation = (
            f"{organisation}, {country}" if country else organisation
        )
        if not organisation:
            return
        target = AffiliationTarget(
            organisation=organisation,
            country=country,
            affiliation=affiliation,
        )
        targets[target.key] = target

    talks = load_talks()
    for _, row in talks.iterrows():
        affiliation_raw = row.get("affiliation")
        if pd.isna(affiliation_raw):
            continue
        affiliation = str(affiliation_raw).strip()
        if not affiliation:
            continue

        parts = [part.strip() for part in affiliation.split(",") if part.strip()]
        organisation = parts[0]
        country = parts[1] if len(parts) > 1 else ""
        if not country:
            presenter = str(row.get("presenter") or "").strip()
            match = delegate_by_name.get(normalize_person_name(presenter)) or delegate_by_name.get(
                presenter.casefold()
            )
            if match:
                organisation, country = match
                affiliation = (
                    f"{organisation}, {country}" if country else organisation
                )
        add(organisation, country)

    for _, row in delegates.iterrows():
        organisation = str(row.get("organisation") or "").strip()
        country = str(row.get("country") or "").strip()
        if not organisation:
            continue
        add(organisation, country)

    by_org: dict[str, list[AffiliationTarget]] = {}
    for target in targets.values():
        by_org.setdefault(target.organisation.casefold(), []).append(target)
    filtered: dict[tuple[str, str], AffiliationTarget] = {}
    for group in by_org.values():
        with_country = [item for item in group if item.country]
        keep = with_country or group
        for target in keep:
            filtered[target.key] = target

    return sorted(filtered.values(), key=lambda item: item.affiliation.casefold())


def _google_geocode_query(
    query: str,
    *,
    api_key: str,
    pause_seconds: float = 0.05,
) -> dict[str, Any]:
    params = urlencode({"address": query, "key": api_key})
    response = requests.get(f"{_GOOGLE_GEOCODE_URL}?{params}", timeout=20)
    response.raise_for_status()
    payload = response.json()
    time.sleep(pause_seconds)
    return payload


def geocode_target(
    target: AffiliationTarget,
    *,
    api_key: str,
    pause_seconds: float = 0.05,
) -> dict[str, Any]:
    query = target.geocode_query()
    try:
        payload = _google_geocode_query(
            query, api_key=api_key, pause_seconds=pause_seconds
        )
    except requests.RequestException as exc:
        return {
            "organisation": target.organisation,
            "country": target.country,
            "affiliation": target.affiliation,
            "query_used": query,
            "latitude": math.nan,
            "longitude": math.nan,
            "formatted_address": "",
            "status": f"error:{exc.__class__.__name__}",
        }

    status = payload.get("status")
    if status == "ZERO_RESULTS":
        return {
            "organisation": target.organisation,
            "country": target.country,
            "affiliation": target.affiliation,
            "query_used": query,
            "latitude": math.nan,
            "longitude": math.nan,
            "formatted_address": "",
            "status": "ZERO_RESULTS",
        }
    if status != "OK":
        return {
            "organisation": target.organisation,
            "country": target.country,
            "affiliation": target.affiliation,
            "query_used": query,
            "latitude": math.nan,
            "longitude": math.nan,
            "formatted_address": "",
            "status": str(status),
        }

    results = payload.get("results") or []
    if not results:
        return {
            "organisation": target.organisation,
            "country": target.country,
            "affiliation": target.affiliation,
            "query_used": query,
            "latitude": math.nan,
            "longitude": math.nan,
            "formatted_address": "",
            "status": "ZERO_RESULTS",
        }

    top = results[0]
    if not _google_result_is_precise(top):
        return {
            "organisation": target.organisation,
            "country": target.country,
            "affiliation": target.affiliation,
            "query_used": query,
            "latitude": math.nan,
            "longitude": math.nan,
            "formatted_address": top.get("formatted_address") or "",
            "status": "IMPRECISE",
        }

    location = top.get("geometry", {}).get("location") or {}
    lat = location.get("lat")
    lon = location.get("lng")
    if lat is None or lon is None:
        return {
            "organisation": target.organisation,
            "country": target.country,
            "affiliation": target.affiliation,
            "query_used": query,
            "latitude": math.nan,
            "longitude": math.nan,
            "formatted_address": top.get("formatted_address") or "",
            "status": "NO_COORDS",
        }

    return {
        "organisation": target.organisation,
        "country": target.country,
        "affiliation": target.affiliation,
        "query_used": query,
        "latitude": float(lat),
        "longitude": float(lon),
        "formatted_address": top.get("formatted_address") or "",
        "status": "OK",
    }


def geocode_all_affiliations(
    targets: list[AffiliationTarget] | None = None,
    *,
    pause_seconds: float = 0.05,
    show_progress: bool = True,
) -> pd.DataFrame:
    """Geocode every affiliation target via Google Maps (no cache reads/writes)."""
    if targets is None:
        targets = collect_affiliation_targets()
    api_key = load_google_maps_api_key()

    rows: list[dict[str, Any]] = []
    progress = Progress(
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TaskProgressColumn(),
        TimeElapsedColumn(),
        console=_CONSOLE,
        disable=not show_progress,
    )
    with progress:
        task_id = progress.add_task("Geocoding affiliations", total=len(targets))
        for target in targets:
            rows.append(
                geocode_target(
                    target, api_key=api_key, pause_seconds=pause_seconds
                )
            )
            progress.advance(task_id)

    return pd.DataFrame(rows)
