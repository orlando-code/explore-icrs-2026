#!/usr/bin/env python3
"""Fetch World Bank national per-capita CO₂ and refresh emissions comparisons."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.travel_emissions import (
    DEFAULT_EMISSIONS_SITE_PATH,
    DEFAULT_NATIONAL_PER_CAPITA_PATH,
    NATIONAL_PER_CAPITA_YEAR,
    fetch_world_bank_national_per_capita,
    refresh_emissions_site_national_context,
    save_national_per_capita,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Download World Bank EN.GHG.CO2.PC.CE.AR5 per-capita CO₂ data and "
            "refresh national comparison context in js/emissions-data.js."
        )
    )
    parser.add_argument(
        "--year",
        type=int,
        default=NATIONAL_PER_CAPITA_YEAR,
        help="World Bank data year to request (default: 2024).",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_NATIONAL_PER_CAPITA_PATH,
        help="Path for national per-capita JSON cache.",
    )
    parser.add_argument(
        "--site-output",
        type=Path,
        default=DEFAULT_EMISSIONS_SITE_PATH,
        help="Path for emissions tab JS export to refresh.",
    )
    parser.add_argument(
        "--skip-site-refresh",
        action="store_true",
        help="Only update data/national_per_capita_co2.json.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    data = fetch_world_bank_national_per_capita(year=args.year)
    save_national_per_capita(data, args.output)
    print(
        f"Wrote {args.output} ({len(data['countries']):,} countries, "
        f"year {data['meta']['year']})."
    )
    if not args.skip_site_refresh and args.site_output.exists():
        refresh_emissions_site_national_context(args.site_output)
        print(f"Refreshed national context in {args.site_output}.")
    elif not args.skip_site_refresh:
        print(f"Skipped site refresh: {args.site_output} not found.")


if __name__ == "__main__":
    main()
