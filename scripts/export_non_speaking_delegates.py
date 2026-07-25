#!/usr/bin/env python3
"""Export non-speaking delegate names for the map site."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.delegates import (
    export_non_speaking_delegates_js,
    load_delegates,
    non_speaking_delegate_groups,
)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        default="js/non-speaking-delegates.js",
        help="Path for generated JS module.",
    )
    args = parser.parse_args()

    delegates = load_delegates()
    group_list = non_speaking_delegate_groups(delegates)
    output = export_non_speaking_delegates_js(args.output, delegates=delegates)
    delegate_count = sum(len(group["delegates"]) for group in group_list)
    print(
        f"Wrote {output} ({delegate_count:,} delegates across {len(group_list):,} affiliations)"
    )


if __name__ == "__main__":
    main()
