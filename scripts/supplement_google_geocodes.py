#!/usr/bin/env python3
"""Supplement Nominatim geocodes with Google Maps Geocoding API."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.delegates import load_delegates
from src.google_geocode import supplement_with_google_geocodes
from src.programme import load_talks


def _collect_affiliations(include_delegates: bool) -> list[str]:
    talks = load_talks()
    affiliations = {
        str(value).strip()
        for value in talks["affiliation"].dropna().unique()
        if str(value).strip()
    }
    if include_delegates:
        delegates = load_delegates()
        column = "affiliation" if "affiliation" in delegates.columns else "organisation"
        affiliations.update(
            str(value).strip()
            for value in delegates[column].dropna().unique()
            if str(value).strip()
        )
    return sorted(affiliations)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--keys-path",
        type=Path,
        default=PROJECT_ROOT / "keys.yaml",
        help="YAML file containing google_maps_api_key",
    )
    parser.add_argument(
        "--include-delegates",
        action="store_true",
        help="Also geocode non-speaking delegate affiliations",
    )
    parser.add_argument(
        "--distance-km",
        type=float,
        default=10.0,
        help="Flag when Google differs from current coords by more than this (default: 10)",
    )
    parser.add_argument(
        "--pause-seconds",
        type=float,
        default=0.05,
        help="Pause between Google API requests (default: 0.05)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Query Google and report flags without writing geocode caches",
    )
    args = parser.parse_args()

    affiliations = _collect_affiliations(include_delegates=args.include_delegates)
    supplement_with_google_geocodes(
        affiliations,
        keys_path=args.keys_path,
        distance_flag_km=args.distance_km,
        pause_seconds=args.pause_seconds,
        dry_run=args.dry_run,
        show_progress=True,
    )


if __name__ == "__main__":
    main()
