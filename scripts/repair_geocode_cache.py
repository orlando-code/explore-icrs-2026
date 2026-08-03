#!/usr/bin/env python3
"""Purge corrupted geocode cache entries and re-query Nominatim for affected affiliations."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.geocode import (
    DEFAULT_CACHE_PATH,
    _load_json,
    _save_cache,
    geocode_affiliations,
    is_crf_cache_poison,
)


def purge_poisoned_cache(
    cache_path: Path = DEFAULT_CACHE_PATH,
    *,
    dry_run: bool = False,
) -> list[str]:
    cache = _load_json(cache_path)
    purged: list[str] = []
    for affiliation, coords in list(cache.items()):
        if not is_crf_cache_poison(affiliation, coords):
            continue
        purged.append(affiliation)
        if dry_run:
            continue
        cache[affiliation] = {
            "latitude": None,
            "longitude": None,
            "query_used": None,
            "geocode_level": None,
        }
    if not dry_run and purged:
        _save_cache(cache_path, cache)
    return sorted(purged, key=str.casefold)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--cache",
        type=Path,
        default=DEFAULT_CACHE_PATH,
        help="Path to geocode_cache.json",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="List poisoned affiliations without modifying the cache",
    )
    parser.add_argument(
        "--purge-only",
        action="store_true",
        help="Purge poisoned entries but do not re-geocode",
    )
    parser.add_argument(
        "--pause",
        type=float,
        default=0.1,
        help="Pause between Nominatim queries (seconds)",
    )
    args = parser.parse_args()

    purged = purge_poisoned_cache(args.cache, dry_run=args.dry_run)
    print(f"Poisoned affiliations: {len(purged):,}")
    for affiliation in purged[:20]:
        print(f"  - {affiliation}")
    if len(purged) > 20:
        print(f"  ... and {len(purged) - 20:,} more")

    if args.dry_run or args.purge_only or not purged:
        return

    print(f"\nRe-geocoding {len(purged):,} affiliations via Nominatim...")
    geocode_affiliations(
        purged,
        cache_path=args.cache,
        pause_seconds=args.pause,
        retry_failed=True,
        upgrade_incomplete=True,
        show_progress=True,
    )


if __name__ == "__main__":
    main()
