#!/usr/bin/env python3
"""Export geocoded affiliation locations for the static JS map site."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.affiliation_geocodes import attach_affiliation_geocodes
from src.delegates import combined_attendee_talks, export_non_speaking_delegates_js, load_delegates
from src.export_progress import console, export_stage, run_with_progress
from src.map_exclusions import export_map_exclusions_js
from src.plot_utils import export_attendee_site_data
from src.programme import load_talks
from src.talks_export import export_talks_catalog


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        default="js/locations.js",
        help="Path to write the generated locations module",
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Disable progress output",
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
    show_progress = not args.quiet

    with export_stage("Loading programme talks"):
        talks = load_talks()
    if show_progress:
        console().print(f"  {len(talks):,} talks loaded")

    with export_stage("Attaching affiliation geocodes"):
        talks_geo = attach_affiliation_geocodes(talks, show_progress=show_progress)

    with export_stage("Loading delegates"):
        delegates = load_delegates()
    if show_progress:
        console().print(f"  {len(delegates):,} delegates loaded")

    with export_stage("Merging delegate locations into talks"):
        talks_geo = combined_attendee_talks(
            talks_geo,
            include_non_speakers=True,
            delegates=delegates,
            show_progress=show_progress,
        )

    with export_stage("Exporting map exclusions"):
        exclusions_output = export_map_exclusions_js()

    with export_stage("Building and writing locations.js"):
        output = export_attendee_site_data(
            talks_geo,
            save_path=args.output,
            show_progress=show_progress,
        )

    with export_stage("Exporting talks catalog"):
        talks_output = export_talks_catalog(talks_geo, show_progress=show_progress)

    with export_stage("Exporting non-speaking delegates"):
        delegates_output = run_with_progress(
            "Writing js/non-speaking-delegates.js",
            lambda: export_non_speaking_delegates_js(
                delegates=delegates,
                show_progress=show_progress,
            ),
            show_progress=show_progress,
        )

    stats = output.read_text(encoding="utf-8").split('"stats":', 1)[-1][:120]
    console().print(f"Wrote {output}")
    console().print(f"Wrote {exclusions_output}")
    console().print(f"Wrote {talks_output}")
    console().print(f"Wrote {delegates_output}")
    console().print(f"Preview: ...stats{stats}...")


if __name__ == "__main__":
    main()
