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
from src.export_progress import console, export_stage
from src.map_exclusions import export_map_exclusions_js


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        default="js/non-speaking-delegates.js",
        help="Path for generated JS module.",
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Disable progress output",
    )
    args = parser.parse_args()
    show_progress = not args.quiet

    with export_stage("Loading delegates"):
        delegates = load_delegates()

    with export_stage("Exporting map exclusions"):
        exclusions_output = export_map_exclusions_js()

    with export_stage("Building delegate groups"):
        group_list = non_speaking_delegate_groups(delegates)

    with export_stage("Writing non-speaking-delegates.js"):
        output = export_non_speaking_delegates_js(
            args.output,
            delegates=delegates,
            show_progress=show_progress,
        )

    delegate_count = sum(len(group["delegates"]) for group in group_list)
    console().print(
        f"Wrote {output} ({delegate_count:,} delegates across {len(group_list):,} affiliations)"
    )
    console().print(f"Wrote {exclusions_output}")


if __name__ == "__main__":
    main()
