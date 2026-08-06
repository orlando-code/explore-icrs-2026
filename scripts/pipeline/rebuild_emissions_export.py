#!/usr/bin/env python3
"""Rebuild emissions-data.js from registry geocodes and emissions.dev route cache."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.emissions.emissions_build import build_emissions_site
from src.site.export_progress import console


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Disable progress output",
    )
    parser.add_argument(
        "--no-fetch",
        action="store_true",
        help="Use travel cache only; do not query emissions.dev for missing routes.",
    )
    parser.add_argument(
        "--requery-all",
        action="store_true",
        help="Re-query every unique route (uses primary API key from keys.yaml).",
    )
    args = parser.parse_args()

    result = build_emissions_site(
        artifacts_dir=PROJECT_ROOT / "pipeline" / "artifacts",
        fetch_missing_routes=not args.no_fetch,
        requery_all_routes=args.requery_all,
        show_progress=not args.quiet,
    )
    console().print(
        f"Rebuilt js/emissions-data.js "
        f"({result.routes_queried} API queries, "
        f"{result.routes_missing_before} routes were missing before build)"
    )


if __name__ == "__main__":
    main()
