#!/usr/bin/env python3
"""Merge manual delegate-ID review edits into a fresh match export."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import pandas as pd

from scripts.export_delegate_id_match_review import (
    DEFAULT_DELEGATES_CSV,
    DEFAULT_ID_DATABASE_CSV,
    build_review_frame,
    load_id_rows,
    norm_name,
    org_agrees,
)

DEFAULT_MANUAL_REVIEW_CSV = PROJECT_ROOT / "data" / "delegate_id_match_review.csv"
DEFAULT_MANUAL_REVIEW_FALLBACK_CSV = (
    PROJECT_ROOT / "data" / "delegate_id_match_review_manually_reviewed_01.csv"
)
DEFAULT_OUTPUT_CSV = PROJECT_ROOT / "data" / "delegate_id_match_review_04_merged.csv"

OUTPUT_COLUMNS = [
    "row_kind",
    "match_tier",
    "reason",
    "candidate_count",
    "delegate_id",
    "delegate_full_name",
    "delegate_first_name",
    "delegate_last_name",
    "delegate_organisation",
    "delegate_country",
    "is_speaker",
    "id_full_name",
    "id_first_name",
    "id_last_name",
    "id_organisation",
    "org_agrees",
    "manually_reviewed",
    "review_notes",
]


def _clean_id(value: object) -> str:
    text = str(value or "").strip()
    if not text or text.lower() == "nan":
        return ""
    if text.endswith(".0"):
        text = text[:-2]
    return text


def _is_confirmed(notes: str) -> bool:
    return str(notes or "").strip().upper() == "TRUE"


def _is_rejected(notes: str) -> bool:
    return str(notes or "").strip().upper() == "FALSE"


def _read_review_csv(path: Path) -> pd.DataFrame:
    for encoding in ("utf-8", "utf-8-sig", "latin-1"):
        try:
            return pd.read_csv(path, dtype=str, encoding=encoding).fillna("")
        except UnicodeDecodeError:
            continue
    return pd.read_csv(path, dtype=str, encoding="latin-1").fillna("")


def _has_review_annotations(frame: pd.DataFrame) -> bool:
    if "review_notes" not in frame.columns:
        return False
    notes = frame["review_notes"].astype(str).str.strip().str.upper()
    return notes.isin({"TRUE", "FALSE"}).any()


def _first_token(value: str) -> str:
    parts = norm_name(value).split()
    return parts[0] if parts else ""


def _delegate_key(row: pd.Series | dict[str, object]) -> str:
    if isinstance(row, pd.Series):
        row = row.to_dict()
    name = norm_name(str(row.get("delegate_full_name") or ""))
    org = norm_name(str(row.get("delegate_organisation") or ""))
    country = norm_name(str(row.get("delegate_country") or ""))
    return f"{name}|{org}|{country}"


def _manual_lookup(
    manual_delegates: pd.DataFrame,
) -> tuple[dict[str, pd.Series], dict[str, pd.Series], dict[str, pd.Series]]:
    by_key: dict[str, pd.Series] = {}
    by_name: dict[str, pd.Series] = {}
    by_id: dict[str, pd.Series] = {}
    for _, row in manual_delegates.iterrows():
        key = _delegate_key(row)
        if key not in by_key:
            by_key[key] = row
        name_key = norm_name(row.get("delegate_full_name"))
        if name_key and name_key not in by_name:
            by_name[name_key] = row
        delegate_id = _clean_id(row.get("delegate_id"))
        if delegate_id and delegate_id not in by_id:
            by_id[delegate_id] = row
    return by_key, by_name, by_id


def _find_manual_row(
    auto_row: pd.Series,
    manual_by_key: dict[str, pd.Series],
    manual_by_name: dict[str, pd.Series],
    manual_by_id: dict[str, pd.Series],
) -> pd.Series | None:
    manual_row = manual_by_key.get(_delegate_key(auto_row))
    if manual_row is not None:
        return manual_row

    key = norm_name(auto_row.get("delegate_full_name"))
    alt_key = norm_name(auto_row.get("delegate_first_name"), auto_row.get("delegate_last_name"))
    manual_row = manual_by_name.get(key)
    if manual_row is None:
        manual_row = manual_by_name.get(alt_key)
    if manual_row is not None:
        return manual_row

    auto_id = _clean_id(auto_row.get("delegate_id"))
    if auto_id:
        manual_row = manual_by_id.get(auto_id)
        if manual_row is not None:
            return manual_row

    organisation = str(auto_row.get("delegate_organisation") or "")
    last = norm_name(auto_row.get("delegate_first_name"), auto_row.get("delegate_last_name"))
    last = (last.split() or [""])[-1]
    for candidate in manual_by_id.values():
        manual_last = norm_name(
            candidate.get("delegate_first_name"),
            candidate.get("delegate_last_name"),
        )
        manual_last = (manual_last.split() or [""])[-1]
        if manual_last != last:
            continue
        if org_agrees(organisation, str(candidate.get("delegate_organisation") or "")):
            return candidate
    return None


def _find_delegate_for_manual_id(
    merged: pd.DataFrame,
    manual_id: str,
    id_row: dict[str, str],
) -> int | None:
    existing = merged[
        (merged["row_kind"] == "delegate") & (merged["delegate_id"] == manual_id)
    ]
    if len(existing) == 1:
        return int(existing.index[0])

    id_norm = norm_name(id_row.get("id_first_name", ""), id_row.get("id_last_name", ""))
    id_org = str(id_row.get("id_organisation") or "")
    id_first = _first_token(id_row.get("id_first_name", ""))

    delegate_rows = merged[merged["row_kind"] == "delegate"]
    for idx, delegate_row in delegate_rows.iterrows():
        delegate_norm = norm_name(
            delegate_row.get("delegate_first_name"),
            delegate_row.get("delegate_last_name"),
        )
        if not delegate_norm:
            delegate_norm = norm_name(delegate_row.get("delegate_full_name"))
        if id_norm and delegate_norm == id_norm:
            return int(idx)

    org_matches: list[int] = []
    for idx, delegate_row in delegate_rows.iterrows():
        if not org_agrees(str(delegate_row.get("delegate_organisation") or ""), id_org):
            continue
        delegate_first = _first_token(
            str(delegate_row.get("delegate_first_name") or delegate_row.get("delegate_full_name"))
        )
        if id_first and delegate_first and (
            id_first == delegate_first
            or id_first.startswith(delegate_first)
            or delegate_first.startswith(id_first)
        ):
            org_matches.append(int(idx))

    if len(org_matches) == 1:
        return org_matches[0]

    if len(org_matches) > 1:
        unmatched = [
            idx
            for idx in org_matches
            if str(merged.at[idx, "match_tier"]) == "unmatched"
        ]
        if len(unmatched) == 1:
            return unmatched[0]
    return None


def _apply_manual_match(
    row: dict[str, object],
    manual_row: pd.Series,
    auto_row: dict[str, object],
    id_index: dict[str, dict[str, str]],
) -> None:
    notes = str(manual_row.get("review_notes") or "").strip()
    row["review_notes"] = notes

    if _is_rejected(notes):
        row.clear()
        row.update(auto_row)
        row["delegate_id"] = ""
        row["id_full_name"] = ""
        row["id_first_name"] = ""
        row["id_last_name"] = ""
        row["id_organisation"] = ""
        row["manually_reviewed"] = "FALSE"
        row["review_notes"] = "FALSE"
        row["match_tier"] = "partial" if row.get("match_tier") == "perfect" else row.get("match_tier")
        if row.get("match_tier") in {"confirmed", "perfect"}:
            row["match_tier"] = "partial"
        row["reason"] = "manually_rejected"
        row["org_agrees"] = False
        return

    manually_reviewed = _is_confirmed(notes)
    manual_id = _clean_id(manual_row.get("delegate_id"))
    if manual_id:
        row["delegate_id"] = manual_id
        id_row = id_index.get(manual_id, {})
        if id_row:
            row["id_full_name"] = id_row["id_full_name"]
            row["id_first_name"] = id_row["id_first_name"]
            row["id_last_name"] = id_row["id_last_name"]
            row["id_organisation"] = id_row["id_organisation"]
        else:
            row["id_full_name"] = str(manual_row.get("id_full_name") or "").strip()
            row["id_first_name"] = str(manual_row.get("id_first_name") or "").strip()
            row["id_last_name"] = str(manual_row.get("id_last_name") or "").strip()
            row["id_organisation"] = str(manual_row.get("id_organisation") or "").strip()

    if manually_reviewed and _clean_id(row.get("delegate_id")):
        row["match_tier"] = "confirmed"
        row["reason"] = "manually_confirmed"
    elif manual_id and row.get("match_tier") == "unmatched":
        row["match_tier"] = "partial"
        row["reason"] = "manual_id_assignment"

    row["manually_reviewed"] = "TRUE" if manually_reviewed else "FALSE"
    row["org_agrees"] = bool(
        row.get("delegate_id")
        and org_agrees(
            str(row.get("delegate_organisation") or ""),
            str(row.get("id_organisation") or ""),
        )
    )


def _resolve_manual_review_path(manual_path: Path | None = None) -> Path:
    if manual_path is not None:
        return manual_path

    data_dir = PROJECT_ROOT / "data"
    merged_candidates = sorted(
        data_dir.glob("delegate_id_match_review_*_merged.csv"),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    for path in merged_candidates:
        if _has_review_annotations(_read_review_csv(path)):
            return path

    if DEFAULT_MANUAL_REVIEW_CSV.exists():
        frame = _read_review_csv(DEFAULT_MANUAL_REVIEW_CSV)
        if _has_review_annotations(frame):
            return DEFAULT_MANUAL_REVIEW_CSV
    return DEFAULT_MANUAL_REVIEW_FALLBACK_CSV


def merge_manual_review(
    *,
    manual_path: Path | None = None,
    delegates_path: Path = DEFAULT_DELEGATES_CSV,
    id_database_path: Path = DEFAULT_ID_DATABASE_CSV,
) -> pd.DataFrame:
    manual_path = _resolve_manual_review_path(manual_path)
    manual = _read_review_csv(manual_path)
    auto = build_review_frame(
        delegates_path=delegates_path,
        id_database_path=id_database_path,
    )
    manual_delegates = manual[manual["row_kind"] == "delegate"].copy().reset_index(drop=True)
    manual_by_key, manual_by_name, manual_by_id = _manual_lookup(manual_delegates)

    id_rows = load_id_rows(id_database_path)
    id_index = {row["delegate_id"]: row for row in id_rows}

    delegate_rows: list[dict[str, object]] = []
    auto_delegates = auto[auto["row_kind"] == "delegate"].copy().reset_index(drop=True)
    for row_index, (_, auto_row) in enumerate(auto_delegates.iterrows()):
        auto_dict = auto_row.to_dict()
        row = dict(auto_dict)
        manual_row = None
        if row_index < len(manual_delegates):
            manual_row = manual_delegates.iloc[row_index]
        if manual_row is None or not str(manual_row.get("delegate_full_name") or "").strip():
            manual_row = _find_manual_row(auto_row, manual_by_key, manual_by_name, manual_by_id)
        if manual_row is not None:
            _apply_manual_match(row, manual_row, auto_dict, id_index)
        else:
            row["delegate_id"] = _clean_id(row.get("delegate_id"))
            row["manually_reviewed"] = "FALSE"
            row["review_notes"] = ""
            row["org_agrees"] = bool(
                row.get("delegate_id")
                and org_agrees(
                    str(row.get("delegate_organisation") or ""),
                    str(row.get("id_organisation") or ""),
                )
            )
        delegate_rows.append(row)

    merged = pd.DataFrame(delegate_rows)

    rejected_ids = {
        _clean_id(manual_row.get("delegate_id"))
        for _, manual_row in manual_delegates.iterrows()
        if _is_rejected(manual_row.get("review_notes", ""))
    }
    rejected_ids.discard("")

    for _, manual_row in manual_delegates.iterrows():
        if _is_rejected(manual_row.get("review_notes", "")):
            continue
        if not _is_confirmed(manual_row.get("review_notes", "")):
            continue
        manual_id = _clean_id(manual_row.get("delegate_id"))
        if not manual_id or manual_id in rejected_ids:
            continue
        already_confirmed = (
            (merged["row_kind"] == "delegate")
            & (merged["delegate_id"] == manual_id)
            & (merged["manually_reviewed"].str.upper() == "TRUE")
            & (merged["match_tier"] == "confirmed")
        )
        if already_confirmed.any():
            continue

        target_idx = _find_delegate_for_manual_id(
            merged, manual_id, id_index.get(manual_id, {})
        )
        if target_idx is None:
            continue

        updated = merged.loc[target_idx].to_dict()
        auto_match = auto[auto["delegate_full_name"] == updated["delegate_full_name"]]
        auto_dict = auto_match.iloc[0].to_dict() if len(auto_match) else updated
        _apply_manual_match(updated, manual_row, auto_dict, id_index)
        for key, value in updated.items():
            merged.at[target_idx, key] = value

    assigned_ids = {
        delegate_id
        for delegate_id in merged["delegate_id"].astype(str)
        if _clean_id(delegate_id)
    }

    id_only_rows: list[dict[str, object]] = []
    for row in id_rows:
        if row["delegate_id"] in assigned_ids:
            continue
        id_only_rows.append(
            {
                "row_kind": "id_only",
                "match_tier": "id_unmatched",
                "reason": "no_delegate_match",
                "candidate_count": 0,
                "delegate_id": row["delegate_id"],
                "delegate_full_name": "",
                "delegate_first_name": "",
                "delegate_last_name": "",
                "delegate_organisation": "",
                "delegate_country": "",
                "is_speaker": "",
                "id_full_name": row["id_full_name"],
                "id_first_name": row["id_first_name"],
                "id_last_name": row["id_last_name"],
                "id_organisation": row["id_organisation"],
                "org_agrees": False,
                "manually_reviewed": "FALSE",
                "review_notes": "",
            }
        )

    output = pd.concat([merged, pd.DataFrame(id_only_rows)], ignore_index=True)
    return output[OUTPUT_COLUMNS]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--manual",
        type=Path,
        default=None,
        help="Manual review CSV (defaults to delegate_id_match_review.csv if it has TRUE flags)",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT_CSV,
        help="Merged output CSV path",
    )
    args = parser.parse_args()

    manual_path = _resolve_manual_review_path(args.manual)
    frame = merge_manual_review(manual_path=manual_path)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(args.output, index=False, encoding="utf-8")

    delegates = frame[frame["row_kind"] == "delegate"]
    summary = delegates["match_tier"].value_counts().to_dict()
    confirmed = int((delegates["manually_reviewed"].str.upper() == "TRUE").sum())
    print(f"Manual source: {manual_path}")
    print(f"Wrote {args.output} ({len(frame)} rows)")
    print(
        "Delegate tiers:",
        ", ".join(f"{key}={value}" for key, value in sorted(summary.items())),
    )
    print(f"Manually confirmed: {confirmed}")
    print(f"Still partial: {int((delegates['match_tier'] == 'partial').sum())}")
    print(f"Delegates still unmatched: {int((delegates['match_tier'] == 'unmatched').sum())}")
    print(f"IDs with no delegate match: {int((frame['row_kind'] == 'id_only').sum())}")


if __name__ == "__main__":
    main()
