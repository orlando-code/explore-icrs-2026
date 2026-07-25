#!/usr/bin/env python3
"""Export talk catalog for the network talk detail panel."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.talks_export import export_talks_catalog
from src.programme import load_talks


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        default="js/talks.js",
        help="Path to write the generated talks module",
    )
    args = parser.parse_args()

    talks = load_talks()
    output = export_talks_catalog(talks, save_path=args.output)
    print(f"Wrote {output} ({talks.shape[0]} programme rows)")
    print("Run scripts/build_talk_similarities.py to refresh js/talk-similarities.js")


if __name__ == "__main__":
    main()
