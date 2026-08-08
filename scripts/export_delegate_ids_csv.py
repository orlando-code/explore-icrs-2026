#!/usr/bin/env python3
"""Export name→delegate_id CSV for the offset API (local only — never commit)."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.registry.person_registry import (  # noqa: E402
    DEFAULT_OFFICIAL_IDS_PATH,
    load_official_delegate_ids,
)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--input",
        type=Path,
        default=DEFAULT_OFFICIAL_IDS_PATH,
        help="Local person_registry_official_ids.csv (gitignored)",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=PROJECT_ROOT / "backend" / "data" / "delegate_ids.csv",
        help="API CSV path (gitignored)",
    )
    parser.add_argument(
        "--sample",
        type=int,
        default=0,
        help="If set, write only the first N rows (for local docker smoke tests)",
    )
    args = parser.parse_args()

    official_ids = load_official_delegate_ids(args.input)
    if official_ids.empty:
        raise SystemExit(
            f"No official delegate IDs at {args.input}. "
            "Run: python scripts/pipeline/build_pipeline.py registry"
        )

    rows = official_ids.loc[
        official_ids["official_delegate_id"].astype(str).str.strip().ne("")
    ].copy()
    if args.sample > 0:
        rows = rows.head(args.sample)

    output = rows.rename(
        columns={"canonical_name": "name", "official_delegate_id": "delegate_id"}
    )[["name", "delegate_id"]]
    args.output.parent.mkdir(parents=True, exist_ok=True)
    output.to_csv(args.output, index=False)
    print(f"Wrote {len(output):,} rows to {args.output}")


if __name__ == "__main__":
    main()
