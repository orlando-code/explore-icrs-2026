#!/usr/bin/env python3
"""Export geocoded affiliation locations for the static JS map site."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.geocoding.affiliation_geocodes import export_geocode_overrides_js
from src.sources.delegates import export_non_speaking_delegates_js, load_delegates
from src.site.export_progress import console, export_stage, run_with_progress
from src.site.map_exclusions import export_map_exclusions_js
from src.site.plot_utils import export_attendee_site_data
from src.registry.registry_export import build_map_talks
from src.site.talks_export import export_talks_catalog


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
    args = parser.parse_args()
    show_progress = not args.quiet

    with export_stage("Building registry-backed map talks"):
        talks_geo = build_map_talks(show_progress=show_progress)
    if show_progress:
        console().print(f"  {len(talks_geo):,} attendee rows")

    with export_stage("Loading delegates"):
        delegates = load_delegates()
    if show_progress:
        console().print(f"  {len(delegates):,} delegates loaded")

    with export_stage("Exporting map exclusions"):
        exclusions_output = export_map_exclusions_js()

    with export_stage("Exporting geocode overrides"):
        overrides_output = export_geocode_overrides_js()

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
    console().print(f"Wrote {overrides_output}")
    console().print(f"Wrote {talks_output}")
    console().print(f"Wrote {delegates_output}")
    console().print(f"Preview: ...stats{stats}...")


if __name__ == "__main__":
    main()
