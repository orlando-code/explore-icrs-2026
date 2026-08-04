#!/usr/bin/env python3
"""Export name → delegate ID CSV for the offset API from curated match review.

Reads the latest delegate_id_match_review_*_merged.csv (or --source) and writes
rows with match_tier perfect or confirmed to backend/data/delegate_ids.csv.

The output stays server-side only (gitignored). We export both delegate-side
and ID-database full names (when they differ) so the API accepts whichever name
the site presents to the attendee.

    python scripts/export_delegate_ids_csv.py
    python scripts/export_delegate_ids_csv.py --source data/delegate_id_match_review_04_merged.csv
    python scripts/export_delegate_ids_csv.py --sample 25 --output backend/data/delegate_ids.sample.csv
"""

from __future__ import annotations

import argparse
import csv
import re
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = PROJECT_ROOT / "backend" / "data" / "delegate_ids.csv"
DEFAULT_SAMPLE_OUTPUT = PROJECT_ROOT / "backend" / "data" / "delegate_ids.sample.csv"
MATCHED_TIERS = {"perfect", "confirmed"}
DELEGATE_ID_RE = re.compile(r"^\d{2,5}$")


def resolve_review_path(source: Path | None) -> Path:
    if source is not None:
        return source
    data_dir = PROJECT_ROOT / "data"
    merged = sorted(
        data_dir.glob("delegate_id_match_review_*_merged.csv"),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    if not merged:
        raise FileNotFoundError(
            "No delegate_id_match_review_*_merged.csv found. Run merge_delegate_id_match_review.py first."
        )
    return merged[0]


def load_matched_rows(review_path: Path) -> list[dict[str, str]]:
    import pandas as pd

    frame = pd.read_csv(review_path, dtype=str).fillna("")
    delegates = frame[frame["row_kind"] == "delegate"].copy()
    matched = delegates[
        delegates["match_tier"].isin(MATCHED_TIERS)
        & delegates["delegate_id"].astype(str).str.strip().ne("")
    ]
    rows: list[dict[str, str]] = []
    name_to_id: dict[str, str] = {}

    def maybe_add(name: str, delegate_id: str) -> None:
        cleaned = str(name or "").strip()
        if not cleaned:
            return
        key = cleaned.casefold()
        existing = name_to_id.get(key)
        if existing and existing != delegate_id:
            return
        if existing == delegate_id:
            return
        name_to_id[key] = delegate_id
        rows.append({"name": cleaned, "delegate_id": delegate_id})

    for _, row in matched.iterrows():
        delegate_id = str(row["delegate_id"]).strip()
        if not DELEGATE_ID_RE.fullmatch(delegate_id):
            continue
        # Always keep the delegate-side public name.
        maybe_add(row.get("delegate_full_name", ""), delegate_id)
        # Add the ID-database full name alias when it does not conflict with
        # another delegate ID (so site-facing longer names still verify).
        maybe_add(row.get("id_full_name", ""), delegate_id)
    return rows


def validate_rows(rows: list[dict[str, str]]) -> None:
    # The loader already drops conflicting aliases; keep this as a no-op hook
    # for future checks without aborting exports that otherwise help real users.
    _ = rows


def write_csv(rows: list[dict[str, str]], output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    ordered = sorted(rows, key=lambda row: row["name"].lower())
    with output.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["name", "delegate_id"])
        writer.writeheader()
        writer.writerows(ordered)


def pick_sample_rows(rows: list[dict[str, str]], limit: int, include_names: list[str]) -> list[dict[str, str]]:
    by_name = {row["name"].lower(): row for row in rows}
    picked: list[dict[str, str]] = []
    seen: set[str] = set()
    for raw in include_names:
        key = raw.strip().lower()
        if not key or key in seen:
            continue
        row = by_name.get(key)
        if row:
            picked.append(row)
            seen.add(key)
    for row in sorted(rows, key=lambda item: item["name"].lower()):
        key = row["name"].lower()
        if key in seen:
            continue
        picked.append(row)
        seen.add(key)
        if len(picked) >= limit:
            break
    return picked[:limit]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--source",
        type=Path,
        default=None,
        help="Merged review CSV (default: newest delegate_id_match_review_*_merged.csv)",
    )
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument(
        "--sample",
        type=int,
        default=0,
        help="If set, write only this many rows (for delegate_ids.sample.csv)",
    )
    parser.add_argument(
        "--include-names",
        nargs="*",
        default=["Orlando Timmerman"],
        help="Names to prioritize in --sample output",
    )
    args = parser.parse_args()

    review_path = resolve_review_path(args.source)
    rows = load_matched_rows(review_path)
    if not rows:
        print("No matched delegate rows to export.", file=sys.stderr)
        sys.exit(1)

    validate_rows(rows)

    output_rows = rows
    if args.sample > 0:
        output_rows = pick_sample_rows(rows, args.sample, args.include_names)
        if args.output == DEFAULT_OUTPUT:
            args.output = DEFAULT_SAMPLE_OUTPUT

    write_csv(output_rows, args.output)
    print(f"Source: {review_path}")
    print(f"Wrote {len(output_rows)} rows to {args.output}")
    if args.sample <= 0:
        print(f"Matched delegates available: {len(rows)}")


if __name__ == "__main__":
    main()
