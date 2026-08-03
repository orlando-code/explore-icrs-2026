#!/usr/bin/env python3
"""Rebuild emissions JS export using existing co2e totals and refreshed geocode legs."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.delegates import combined_attendee_talks, load_delegates
from src.travel_emissions import (
    DEFAULT_EMISSIONS_SITE_PATH,
    export_emissions_site_data,
    load_attendee_legs,
    load_geocoded_talks,
    load_site_locations,
)


def _read_emissions_js(path: Path) -> dict:
    source = path.read_text(encoding="utf-8")
    match = re.search(r"export const EMISSIONS_DATA = (\{.*\});\s*$", source, re.S)
    if not match:
        raise ValueError(f"Could not parse emissions export in {path}")
    return json.loads(match.group(1))


def _pool_to_estimates(pool: dict) -> pd.DataFrame:
    rows = []
    for attendee in pool.get("attendees", []):
        rows.append(
            {
                "presenter": attendee.get("name"),
                "affiliation": attendee.get("affiliation"),
                "co2e_kg": attendee.get("co2e_kg"),
                "co2e_low_kg": attendee.get("co2e_kg"),
                "co2e_high_kg": attendee.get("co2e_kg"),
                "origin_country": attendee.get("origin_country"),
                "transport_mode": "flight",
            }
        )
    return pd.DataFrame(rows)


def _pool_to_summary(pool: dict) -> dict:
    headline = pool.get("meta", {}).get("headline", {})
    return {
        "attendees_estimated": headline.get("attendees_estimated", len(pool.get("attendees", []))),
        "attendees_missing_location": headline.get("attendees_missing_location", 0),
        "co2e_kg": headline.get("co2e_kg", 0),
        "co2e_low_kg": headline.get("co2e_low_kg", headline.get("co2e_kg", 0)),
        "co2e_high_kg": headline.get("co2e_high_kg", headline.get("co2e_kg", 0)),
        "co2e_tonnes": headline.get("co2e_tonnes", 0),
        "unique_routes_queried": headline.get("unique_routes_queried", 0),
        "api_queries_used": headline.get("api_queries_used", 0),
        "attendee_label": headline.get("attendee_label", "speakers"),
        "assumptions": pool.get("meta", {}).get("assumptions", {}),
        "uncertainty": pool.get("meta", {}).get("uncertainty", {}),
        "by_transport_mode": pool.get("meta", {}).get("by_transport_mode", []),
        "by_country": pool.get("by_country", []),
        "context": pool.get("meta", {}).get("context", {}),
    }


def main() -> None:
    emissions_path = DEFAULT_EMISSIONS_SITE_PATH
    payload = _read_emissions_js(emissions_path)
    speakers_pool = payload["speakers"]
    delegates_pool = payload.get("all_delegates", speakers_pool)

    speaker_estimates = _pool_to_estimates(speakers_pool)
    speaker_summary = _pool_to_summary(speakers_pool)
    delegate_estimates = _pool_to_estimates(delegates_pool)
    delegate_summary = _pool_to_summary(delegates_pool)

    speaker_talks = load_geocoded_talks()
    speaker_legs, _ = load_attendee_legs(speaker_talks, show_progress=True)

    delegates = load_delegates()
    all_talks = combined_attendee_talks(
        speaker_talks,
        include_non_speakers=True,
        delegates=delegates,
        show_progress=False,
    )
    all_legs, _ = load_attendee_legs(all_talks, show_progress=True)

    locations = load_site_locations("js/locations.js")
    export_emissions_site_data(
        speaker_estimates,
        speaker_summary,
        locations,
        legs=speaker_legs,
        all_delegates=(delegate_estimates, delegate_summary, all_legs),
        delegate_meta=payload.get("meta", {}).get("delegate_meta", {}),
        save_path=emissions_path,
    )
    print(f"Rebuilt {emissions_path}")


if __name__ == "__main__":
    main()
