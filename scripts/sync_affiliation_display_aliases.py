#!/usr/bin/env python3
"""Build affiliation display aliases from a reviewed duplicate-summary CSV."""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
from datetime import UTC, datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import pandas as pd

from src.affiliation_matching import affiliation_token_key
from src.geocode import affiliation_base_name, save_affiliation_display_aliases
from src.geocode import DEFAULT_DISPLAY_ALIASES_PATH

DEFAULT_REVIEW_PATH = PROJECT_ROOT / "data" / "affiliation_duplicate_summary_150corrected.csv"


def _csv_cell(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and math.isnan(value):
        return ""
    text = str(value).strip()
    if text.casefold() == "nan":
        return ""
    return text


def _is_true(value: object) -> bool:
    return str(value or "").strip().upper() in {"TRUE", "YES", "1"}


def _unicode_richness(text: str) -> int:
    score = 0
    for char in text:
        if char in "ʻʼéèáàíìóòúùüñäöÄÉÈÁÀÍÌÓÒÚÙÜÑ":
            score += 2
        if ord(char) > 127:
            score += 1
    return score


def _enrich_display_name(name: str, candidates: list[str]) -> str:
    base = str(name or "").strip()
    if not base:
        return base
    token_key = affiliation_token_key(base)
    pool = [base, *[str(item).strip() for item in candidates if str(item).strip()]]
    matches = [item for item in pool if affiliation_token_key(item) == token_key]
    if not matches:
        return base
    return max(matches, key=lambda item: (_unicode_richness(item), len(item)))


def _split_variants(raw: str) -> list[str]:
    return [part.strip() for part in str(raw or "").split("|") if part.strip()]


def build_aliases_from_review(
    review_path: Path,
    *,
    limit: int | None = None,
) -> tuple[dict[str, str], list[str]]:
    frame = pd.read_csv(review_path)
    if limit is not None:
        frame = frame.head(limit)

    aliases: dict[str, str] = {}
    split_clusters: list[str] = []

    for _, row in frame.iterrows():
        cluster_id = str(row.get("cluster_id") or "").strip()
        if _is_true(row.get("approved_canonical")):
            if cluster_id:
                split_clusters.append(cluster_id)
            continue

        confirmed = _csv_cell(row.get("confirmed_same"))
        suggested = _csv_cell(row.get("suggested_canonical"))
        target = confirmed or suggested
        if not target:
            continue

        variants = _split_variants(row.get("variants"))
        display = _enrich_display_name(target, variants + [suggested])

        for variant in variants:
            if variant == display:
                continue
            aliases[variant] = display
            base = affiliation_base_name(variant)
            if base and base != display and base not in aliases:
                aliases[base] = display

    return aliases, split_clusters


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--review",
        type=Path,
        default=DEFAULT_REVIEW_PATH,
        help="Reviewed duplicate-summary CSV",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_DISPLAY_ALIASES_PATH,
        help="Output JSON path for display aliases",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=150,
        help="Only read the first N rows of the review CSV (default: 150)",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Patch js/locations.js and js/emissions-data.js after writing aliases",
    )
    args = parser.parse_args()

    aliases, split_clusters = build_aliases_from_review(args.review, limit=args.limit)
    payload = {
        "updated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "source": str(args.review.relative_to(PROJECT_ROOT)),
        "alias_count": len(aliases),
        "split_clusters": split_clusters,
        "aliases": dict(sorted(aliases.items(), key=lambda item: item[0].casefold())),
    }
    save_affiliation_display_aliases(payload, args.output)
    print(f"Wrote {len(aliases):,} display aliases to {args.output}")
    print(f"Marked {len(split_clusters):,} clusters as genuinely distinct")

    if args.apply:
        import subprocess

        subprocess.run(
            [
                sys.executable,
                str(PROJECT_ROOT / "scripts" / "fix_site_coordinates.py"),
                "--locations-only",
            ],
            check=True,
            cwd=PROJECT_ROOT,
            env={**dict(**os.environ), "PYTHONPATH": str(PROJECT_ROOT)},
        )


if __name__ == "__main__":
    main()
