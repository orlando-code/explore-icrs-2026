#!/usr/bin/env python3
"""Geocode missing affiliations from the registry via Google Maps (cached)."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.geocoding.geocode_refresh import DEFAULT_GEOCODES_CSV, missing_geocode_targets, refresh_geocodes


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_GEOCODES_CSV)
    parser.add_argument("--pause", type=float, default=0.05)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--plot-on-map-only",
        action="store_true",
        help="Only geocode affiliations flagged plot_on_map in the registry",
    )
    args = parser.parse_args()

    targets = missing_geocode_targets(plot_on_map_only=args.plot_on_map_only)
    print(f"Missing geocodes: {len(targets):,} affiliation(s)")
    if not targets:
        return 0

    result = refresh_geocodes(
        targets,
        output_csv=args.output,
        pause_seconds=args.pause,
        dry_run=args.dry_run,
    )
    ok = int((result["status"] == "OK").sum()) if not result.empty else 0
    print(f"Results: {ok:,} OK | {len(result) - ok:,} failed")
    if not args.dry_run:
        print(f"Appended to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
