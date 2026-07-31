#!/usr/bin/env python3
"""Export geocoded affiliation locations for the static JS map site."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.delegates import export_non_speaking_delegates_js
from src.geocode import attach_coordinates, geocode_affiliations
from src.map_exclusions import export_map_exclusions_js
from src.plot_utils import export_attendee_site_data
from src.talks_export import export_talks_catalog
from src.programme import load_talks


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        default="js/locations.js",
        help="Path to write the generated locations module",
    )
    parser.add_argument(
        "--retry-failed",
        action="store_true",
        help="Re-query affiliations that previously failed geocoding",
    )
    parser.add_argument(
        "--refresh-geocodes",
        action="store_true",
        help="Call Nominatim for missing or upgradeable affiliations (slow)",
    )
    parser.add_argument(
        "--upgrade-incomplete",
        action="store_true",
        help="With --refresh-geocodes, retry country-level or implausible cache hits",
    )
    parser.add_argument(
        "--google-geocode",
        action="store_true",
        help="Supplement geocodes with Google Maps Geocoding API (see keys.yaml)",
    )
    args = parser.parse_args()

    talks = load_talks()
    geocoded = geocode_affiliations(
        talks["affiliation"].dropna().unique(),
        retry_failed=args.retry_failed,
        upgrade_incomplete=args.upgrade_incomplete,
        cache_only=not args.refresh_geocodes,
        show_progress=True,
    )
    if args.google_geocode:
        from src.google_geocode import supplement_with_google_geocodes

        supplement_with_google_geocodes(
            talks["affiliation"].dropna().unique(),
            show_progress=True,
        )
        geocoded = geocode_affiliations(
            talks["affiliation"].dropna().unique(),
            cache_only=not args.refresh_geocodes,
            show_progress=False,
        )
    talks_geo = attach_coordinates(talks, geocoded)
    exclusions_output = export_map_exclusions_js()
    output = export_attendee_site_data(talks_geo, save_path=args.output)
    talks_output = export_talks_catalog(talks_geo)
    delegates_output = export_non_speaking_delegates_js()
    stats = output.read_text(encoding="utf-8").split('"stats":', 1)[-1][:120]
    print(f"Wrote {output}")
    print(f"Wrote {exclusions_output}")
    print(f"Wrote {talks_output}")
    print(f"Wrote {delegates_output}")
    print(f"Preview: ...stats{stats}...")


if __name__ == "__main__":
    main()
