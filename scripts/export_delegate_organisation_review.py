#!/usr/bin/env python3
"""Export delegate organisation review CSV for manual correction."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import pandas as pd

from src.delegates import (
    DEFAULT_DELEGATES_JSON_PATH,
    DEFAULT_ORG_OVERRIDES_PATH,
    DEFAULT_ORG_REVIEW_PATH,
    is_incomplete_organisation,
    load_delegates,
    organisation_for_delegate_row,
    sanitize_delegate_organisation,
)
from src.geocode import affiliation_base_name
from src.programme import load_talks


def _collapsed_organisation(value: str) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _talk_affiliation_map() -> dict[str, str]:
    talks = load_talks()
    mapping: dict[str, str] = {}
    for presenter, affiliation in (
        talks[["presenter", "affiliation"]].dropna().drop_duplicates().itertuples(index=False)
    ):
        display = affiliation_base_name(str(affiliation)) or str(affiliation).strip()
        mapping[str(presenter).strip().casefold()] = display
    return mapping


def _needs_review(raw: str, auto: str, suggested: str) -> bool:
    if not raw:
        return False
    if re.search(r"\s{2,}", raw):
        return True
    if re.search(r"\b(?:Dr|Prof|Professor)\.?\s+[A-Z]", raw):
        return True
    if is_incomplete_organisation(auto):
        return True
    if suggested and auto and suggested.casefold() != auto.casefold():
        return True
    if _collapsed_organisation(raw).casefold() != auto.casefold():
        return True
    return False


def build_review_frame() -> pd.DataFrame:
    delegates = load_delegates()
    raw_rows = json.loads(DEFAULT_DELEGATES_JSON_PATH.read_text(encoding="utf-8"))["delegates"]
    raw_by_name = {str(row["full_name"]).strip(): row for row in raw_rows}
    talk_affiliations = _talk_affiliation_map()

    records: list[dict[str, str | bool]] = []
    for _, row in delegates.iterrows():
        full_name = str(row.get("full_name") or "").strip()
        raw_row = raw_by_name.get(full_name, {})
        raw_organisation = _collapsed_organisation(raw_row.get("organisation", row.get("organisation")))
        auto_organisation = sanitize_delegate_organisation(
            str(raw_row.get("organisation") or row.get("organisation") or ""),
            first_name=str(row.get("first_name") or ""),
            last_name=str(row.get("last_name") or ""),
            country=str(row.get("country") or ""),
        )
        suggested = talk_affiliations.get(full_name.casefold(), "")
        final_organisation = organisation_for_delegate_row(row)
        needs = _needs_review(
            str(raw_row.get("organisation") or ""),
            auto_organisation,
            suggested,
        )
        records.append(
            {
                "full_name": full_name,
                "country": str(row.get("country") or ""),
                "is_speaker": bool(row.get("is_speaker")),
                "raw_organisation": raw_organisation,
                "auto_organisation": auto_organisation,
                "suggested_organisation": suggested,
                "final_organisation": final_organisation,
                "needs_review": needs,
                "notes": "",
            }
        )

    frame = pd.DataFrame(records)
    return frame.sort_values(["needs_review", "full_name"], ascending=[False, True])


def export_review_csv(path: Path = DEFAULT_ORG_REVIEW_PATH) -> Path:
    frame = build_review_frame()
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(path, index=False)
    return path


def sync_overrides_from_review(
    review_path: Path = DEFAULT_ORG_REVIEW_PATH,
    overrides_path: Path = DEFAULT_ORG_OVERRIDES_PATH,
) -> Path:
    """Copy reviewed final_organisation values into the overrides CSV."""
    review = pd.read_csv(review_path)
    review["final_organisation"] = review["final_organisation"].fillna("").astype(str).str.strip()
    review["auto_organisation"] = review["auto_organisation"].fillna("").astype(str).str.strip()
    review["notes"] = review["notes"].fillna("").astype(str).str.strip()

    changed = review[review["final_organisation"] != review["auto_organisation"]].copy()
    changed = changed[changed["final_organisation"].astype(bool)]
    output = changed[["full_name", "final_organisation", "notes"]].rename(
        columns={"final_organisation": "organisation"}
    )
    missing_notes = ~output["notes"].astype(bool)
    output.loc[missing_notes, "notes"] = (
        changed.loc[missing_notes, "raw_organisation"].astype(str).str.slice(0, 120)
    )
    output = output.sort_values("full_name")
    overrides_path.parent.mkdir(parents=True, exist_ok=True)
    output.to_csv(overrides_path, index=False)
    return overrides_path


def export_overrides_template(path: Path = DEFAULT_ORG_OVERRIDES_PATH) -> Path:
    """Create overrides CSV for rows that still need manual confirmation."""
    frame = build_review_frame()
    flagged = frame.loc[frame["needs_review"]].copy()
    flagged["organisation"] = flagged["suggested_organisation"].fillna("")
    flagged["notes"] = flagged["raw_organisation"]
    output = flagged[["full_name", "organisation", "notes"]].copy()

    if path.exists():
        existing = pd.read_csv(path)
        if "full_name" in existing.columns:
            manual = existing[
                existing["organisation"].astype(str).str.strip().astype(bool)
            ]
            output = pd.concat([manual, output], ignore_index=True)
            output = output.drop_duplicates(subset=["full_name"], keep="first")
    output.to_csv(path, index=False)
    return path


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Export or sync delegate organisation CSVs.")
    parser.add_argument(
        "--sync-overrides",
        action="store_true",
        help="Copy final_organisation from review CSV into overrides CSV.",
    )
    args = parser.parse_args()

    if args.sync_overrides:
        overrides_path = sync_overrides_from_review()
        frame = pd.read_csv(DEFAULT_ORG_REVIEW_PATH)
        print(f"Synced {len(pd.read_csv(overrides_path)):,} overrides to {overrides_path}")
        print(f"Review file: {len(frame):,} delegates")
        return

    review_path = export_review_csv()
    overrides_path = export_overrides_template()
    frame = pd.read_csv(review_path)
    flagged = int(frame["needs_review"].sum())
    print(f"Wrote {review_path} ({len(frame):,} delegates; {flagged:,} flagged for review)")
    print(f"Wrote {overrides_path}")
    print(
        "Edit data/delegate_organisation_overrides.csv (organisation column), "
        "then run: PYTHONPATH=. python scripts/export_attendee_site.py && "
        "PYTHONPATH=. python scripts/export_non_speaking_delegates.py && "
        "PYTHONPATH=. python scripts/fix_site_coordinates.py"
    )


if __name__ == "__main__":
    main()
