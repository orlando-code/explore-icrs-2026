#!/usr/bin/env python3
"""Export data/delegates.json (PDF extraction) to CSV for review."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.delegates import DEFAULT_DELEGATES_JSON_PATH, load_delegates


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        type=Path,
        default=PROJECT_ROOT / "data" / "delegates.csv",
        help="CSV output path (default: data/delegates.csv)",
    )
    parser.add_argument(
        "--refresh",
        action="store_true",
        help="Re-parse the delegate PDF before exporting",
    )
    args = parser.parse_args()

    delegates = load_delegates(refresh=args.refresh)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    delegates.to_csv(args.output, index=False)
    print(f"Wrote {len(delegates):,} rows to {args.output}")


if __name__ == "__main__":
    main()
