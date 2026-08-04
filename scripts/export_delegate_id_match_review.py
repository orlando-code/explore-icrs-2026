#!/usr/bin/env python3
"""Export delegate ↔ unique-ID match review CSV (contains secret IDs — keep private)."""

from __future__ import annotations

import re
import sys
import unicodedata
from collections import defaultdict
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import pandas as pd

DEFAULT_DELEGATES_CSV = PROJECT_ROOT / "data" / "delegates.csv"
DEFAULT_ID_DATABASE_CSV = PROJECT_ROOT / "data" / "delegate_unique_id_database.csv"
DEFAULT_OUTPUT_CSV = PROJECT_ROOT / "data" / "delegate_id_match_review.csv"

TITLE_RE = re.compile(r"^(dr|prof|professor|mr|mrs|ms|miss|a/prof)\.?\s+", re.I)


def norm_name(first: str, last: str = "") -> str:
    parts = [TITLE_RE.sub("", str(first or "").strip()), str(last or "").strip()]
    value = " ".join(part for part in parts if part)
    value = unicodedata.normalize("NFKD", value)
    value = "".join(ch for ch in value if not unicodedata.combining(ch))
    value = value.lower()
    value = re.sub(r"[^a-z0-9\s]", " ", value)
    return re.sub(r"\s+", " ", value).strip()


def norm_org(value: str) -> str:
    value = unicodedata.normalize("NFKD", str(value or ""))
    value = "".join(ch for ch in value if not unicodedata.combining(ch))
    value = value.lower()
    value = re.sub(r"[^a-z0-9]+", " ", value)
    return re.sub(r"\s+", " ", value).strip()


def org_agrees(left: str, right: str) -> bool:
    a, b = norm_org(left), norm_org(right)
    if not a or not b:
        return False
    if a == b or a in b or b in a:
        return True
    tokens_a, tokens_b = set(a.split()), set(b.split())
    if not tokens_a or not tokens_b:
        return False
    return len(tokens_a & tokens_b) / max(1, min(len(tokens_a), len(tokens_b))) >= 0.6


def last_name_key(first: str, last: str) -> str:
    parts = norm_name(first, last).split()
    return parts[-1] if parts else ""


def load_id_rows(path: Path) -> list[dict[str, str]]:
    frame = pd.read_csv(path)
    rows: list[dict[str, str]] = []
    for _, record in frame.iterrows():
        first = str(record["First Name"]).strip()
        last = str(record["Last Name"]).strip()
        rows.append(
            {
                "delegate_id": str(record["ID"]).strip(),
                "id_first_name": first,
                "id_last_name": last,
                "id_full_name": f"{first} {last}".strip(),
                "id_organisation": str(record["Organization"]).strip(),
                "norm_name": norm_name(first, last),
                "last_name_key": last_name_key(first, last),
            }
        )
    return rows


def match_delegate_row(
    delegate: pd.Series,
    id_rows: list[dict[str, str]],
    by_norm: dict[str, list[dict[str, str]]],
) -> dict[str, str | bool | int]:
    organisation = str(delegate.get("organisation") or "").strip()
    norm = norm_name(delegate.get("first_name"), delegate.get("last_name"))
    last = last_name_key(delegate.get("first_name"), delegate.get("last_name"))

    match: dict[str, str] | None = None
    match_tier = "unmatched"
    reason = "no_match"
    candidate_count = 0

    candidates = by_norm.get(norm, [])
    if len(candidates) == 1:
        candidate = candidates[0]
        if org_agrees(organisation, candidate["id_organisation"]):
            match, match_tier, reason = candidate, "perfect", "exact_name_org"
        else:
            match, match_tier, reason = candidate, "partial", "exact_name_org_mismatch"
    elif len(candidates) > 1:
        candidate_count = len(candidates)
        org_hits = [row for row in candidates if org_agrees(organisation, row["id_organisation"])]
        if len(org_hits) == 1:
            match, match_tier, reason = org_hits[0], "perfect", "exact_name_disambiguated_by_org"
        else:
            match_tier = "partial"
            reason = (
                f"ambiguous_name_{len(org_hits)}_org_hits"
                if org_hits
                else f"ambiguous_name_{len(candidates)}"
            )
    else:
        org_hits = [
            row
            for row in id_rows
            if row["last_name_key"] == last and org_agrees(organisation, row["id_organisation"])
        ]
        candidate_count = len(org_hits)
        if len(org_hits) == 1:
            match, match_tier, reason = org_hits[0], "partial", "last_name_org_unique"
        elif len(org_hits) > 1:
            match_tier, reason = "partial", f"last_name_org_ambiguous_{len(org_hits)}"

    return {
        "row_kind": "delegate",
        "match_tier": match_tier,
        "reason": reason,
        "candidate_count": candidate_count,
        "delegate_id": match["delegate_id"] if match else "",
        "delegate_full_name": str(delegate.get("full_name") or "").strip(),
        "delegate_first_name": str(delegate.get("first_name") or "").strip(),
        "delegate_last_name": str(delegate.get("last_name") or "").strip(),
        "delegate_organisation": organisation,
        "delegate_country": str(delegate.get("country") or "").strip(),
        "is_speaker": str(delegate.get("is_speaker") or "").strip(),
        "id_full_name": match["id_full_name"] if match else "",
        "id_first_name": match["id_first_name"] if match else "",
        "id_last_name": match["id_last_name"] if match else "",
        "id_organisation": match["id_organisation"] if match else "",
        "org_agrees": bool(match and org_agrees(organisation, match["id_organisation"])),
        "review_notes": "",
    }


def build_review_frame(
    *,
    delegates_path: Path = DEFAULT_DELEGATES_CSV,
    id_database_path: Path = DEFAULT_ID_DATABASE_CSV,
) -> pd.DataFrame:
    delegates = pd.read_csv(delegates_path)
    id_rows = load_id_rows(id_database_path)
    by_norm: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in id_rows:
        by_norm[row["norm_name"]].append(row)

    records = [
        match_delegate_row(delegate, id_rows, by_norm)
        for _, delegate in delegates.iterrows()
    ]

    matched_ids = {
        str(record["delegate_id"])
        for record in records
        if str(record.get("delegate_id") or "").strip()
    }
    for row in id_rows:
        if row["delegate_id"] in matched_ids:
            continue
        records.append(
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
                "review_notes": "",
            }
        )

    columns = [
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
        "review_notes",
    ]
    return pd.DataFrame(records, columns=columns)


def main() -> None:
    output_path = DEFAULT_OUTPUT_CSV
    frame = build_review_frame()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(output_path, index=False)

    delegate_rows = frame[frame["row_kind"] == "delegate"]
    summary = delegate_rows["match_tier"].value_counts().to_dict()
    print(f"Wrote {output_path} ({len(frame)} rows)")
    print(
        "Delegate matches:",
        f"perfect={summary.get('perfect', 0)},",
        f"partial={summary.get('partial', 0)},",
        f"unmatched={summary.get('unmatched', 0)}",
    )
    print(f"Unmatched IDs appended: {int((frame['row_kind'] == 'id_only').sum())}")


if __name__ == "__main__":
    main()
