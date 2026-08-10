"""Build emissions-data.js from registry geocodes and emissions.dev route cache."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd

from src.emissions.travel_emissions import (
    DEFAULT_EMISSIONS_SITE_PATH,
    DEFAULT_KEYS_PATH,
    DEFAULT_TRAVEL_CACHE_PATH,
    MISSING_ROUTES_KEY_NAME,
    TravelEstimate,
    api_query_count,
    attach_route_emissions,
    estimate_unique_routes,
    export_emissions_site_data,
    load_api_key,
    load_attendee_legs,
    routes_from_travel_cache,
    routes_missing_from_cache,
    summarize_travel_emissions,
)
from src.registry.registry_export import _attended_people, build_map_talks
from src.sources.delegates import load_delegates, resolve_compound_affiliation_string
from src.sources.programme import load_talks


@dataclass
class EmissionsBuildResult:
    """Neatly package emissions data from delegate travel information"""

    speaker_legs: pd.DataFrame
    all_legs: pd.DataFrame
    speaker_missing: pd.DataFrame
    all_missing: pd.DataFrame
    routes: pd.DataFrame
    speaker_estimates: pd.DataFrame
    delegate_estimates: pd.DataFrame
    speaker_summary: dict[str, Any]
    delegate_summary: dict[str, Any]
    routes_queried: int
    routes_missing_before: int


def _estimates_from_legs(
    legs: pd.DataFrame,
    routes: pd.DataFrame,
    missing_count: int,
    *,
    attendee_label: str,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Estimate emissions from travel legs"""
    merged = attach_route_emissions(legs, routes).dropna(subset=["co2e_kg"])
    records = [
        TravelEstimate(
            presenter=row["presenter"],
            affiliation=resolve_compound_affiliation_string(str(row["affiliation"])),
            transport_mode=row["transport_mode"],
            origin_country=row["origin_country"],
            origin_location=row["origin_location"],
            geocode_level=row.get("geocode_level"),
            co2e_kg=float(row["co2e_kg"]),
            co2e_low_kg=float(row["co2e_low_kg"]),
            co2e_high_kg=float(row["co2e_high_kg"]),
            distance_km=None
            if pd.isna(row.get("distance_km"))
            else float(row["distance_km"]),
            passengers=1,
            return_trip=True,
            query_used={},
        )
        for _, row in merged.iterrows()
    ]
    estimates = pd.DataFrame([item.__dict__ for item in records])
    summary = summarize_travel_emissions(
        estimates,
        missing_count=missing_count,
        total_presenters=legs["presenter"].nunique(),
        unique_routes=len(routes),
        api_queries=0,
        attendee_label=attendee_label,
        exclusion_note=(
            "Delegates without geocoded affiliations or cached travel routes are excluded."
        ),
    )
    return estimates, summary


def build_emissions_site(
    *,
    emissions_path: Path | str = DEFAULT_EMISSIONS_SITE_PATH,
    keys_path: Path | str = DEFAULT_KEYS_PATH,
    travel_cache_path: Path | str = DEFAULT_TRAVEL_CACHE_PATH,
    artifacts_dir: Path | str | None = None,
    fetch_missing_routes: bool = True,
    requery_all_routes: bool = False,
    show_progress: bool = True,
) -> EmissionsBuildResult:
    """Build js/emissions-data.js from geocoded affiliations and travel route cache."""
    emissions_path = Path(emissions_path)
    keys_path = Path(keys_path)
    travel_cache_path = Path(travel_cache_path)
    artifacts_dir = Path(artifacts_dir) if artifacts_dir else Path("pipeline/artifacts")

    all_talks = build_map_talks(show_progress=show_progress)
    attended_keys = {
        str(row["person_key"]).strip()
        for _, row in _attended_people().iterrows()
        if str(row.get("person_key") or "").strip()
    }
    attended_talks = all_talks[
        all_talks["person_key"].astype(str).str.strip().isin(attended_keys)
    ].copy()

    programme_presenters = {
        str(name).strip()
        for name in load_talks()["presenter"].dropna().astype(str)
        if str(name).strip()
    }
    speaker_talks = attended_talks[
        attended_talks["presenter"].astype(str).str.strip().isin(programme_presenters)
    ].copy()

    speaker_legs, speaker_missing = load_attendee_legs(
        speaker_talks, show_progress=show_progress
    )

    delegates = load_delegates()
    all_legs, all_missing = load_attendee_legs(
        attended_talks, show_progress=show_progress
    )

    missing_before = routes_missing_from_cache(
        all_legs, travel_cache_path=travel_cache_path
    )
    queries_before = api_query_count()

    if requery_all_routes or (fetch_missing_routes and missing_before):
        key_name = None if requery_all_routes else MISSING_ROUTES_KEY_NAME
        api_key = load_api_key(keys_path, key_name=key_name)
        estimate_unique_routes(
            all_legs,
            api_key=api_key,
            travel_cache_path=travel_cache_path,
            show_progress=show_progress,
            missing_only=not requery_all_routes,
            limit=None if requery_all_routes else max(missing_before, 0) or None,
        )

    routes = routes_from_travel_cache(all_legs, travel_cache_path=travel_cache_path)
    speaker_estimates, speaker_summary = _estimates_from_legs(
        speaker_legs, routes, len(speaker_missing), attendee_label="speakers"
    )
    delegate_estimates, delegate_summary = _estimates_from_legs(
        all_legs, routes, len(all_missing), attendee_label="delegates"
    )

    delegate_meta = {
        "delegate_list_count": len(delegates),
        "speaker_count": int(delegates["is_speaker"].sum()),
        "non_speaker_count": int(len(delegates) - delegates["is_speaker"].sum()),
    }

    export_emissions_site_data(
        speaker_estimates,
        speaker_summary,
        legs=speaker_legs,
        all_delegates=(delegate_estimates, delegate_summary, all_legs),
        delegate_meta=delegate_meta,
        save_path=emissions_path,
        show_progress=show_progress,
    )

    artifacts_dir.mkdir(parents=True, exist_ok=True)
    all_legs.to_csv(artifacts_dir / "emissions_travel_legs.csv", index=False)
    all_missing.to_csv(artifacts_dir / "emissions_travel_missing.csv", index=False)
    delegate_estimates.to_csv(
        artifacts_dir / "emissions_delegate_estimates.csv", index=False
    )
    routes.to_csv(artifacts_dir / "emissions_routes.csv", index=False)

    return EmissionsBuildResult(
        speaker_legs=speaker_legs,
        all_legs=all_legs,
        speaker_missing=speaker_missing,
        all_missing=all_missing,
        routes=routes,
        speaker_estimates=speaker_estimates,
        delegate_estimates=delegate_estimates,
        speaker_summary=speaker_summary,
        delegate_summary=delegate_summary,
        routes_queried=api_query_count() - queries_before,
        routes_missing_before=missing_before,
    )
