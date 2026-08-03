#!/usr/bin/env python3
"""Geocode all affiliations with Google Maps and export a review CSV."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.affiliation_geocode import collect_affiliation_targets, geocode_all_affiliations


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        type=Path,
        default=PROJECT_ROOT / "data" / "affiliation_geocodes.csv",
        help="CSV output path (default: data/affiliation_geocodes.csv)",
    )
    parser.add_argument(
        "--pause",
        type=float,
        default=0.05,
        help="Pause between Google API calls (seconds)",
    )
    args = parser.parse_args()

    targets = collect_affiliation_targets()
    print(f"Collected {len(targets):,} unique organisation/country pairs")
    results = geocode_all_affiliations(
        targets, pause_seconds=args.pause, show_progress=True
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    results.to_csv(args.output, index=False)

    ok = int((results["status"] == "OK").sum())
    failed = len(results) - ok
    print(f"Wrote {len(results):,} rows to {args.output}")
    print(f"Geocoded: {ok:,} OK | {failed:,} without coordinates")


if __name__ == "__main__":
    main()
