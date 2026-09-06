#!/usr/bin/env python3
"""Export name→delegate_id CSV for the offset API (local only — never commit)."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.data_paths import PERSON_ALIASES_CSV  # noqa: E402
from src.registry.person_registry import (  # noqa: E402
    DEFAULT_ALIASES_PATH,
    DEFAULT_OFFICIAL_IDS_PATH,
    load_name_aliases,
    load_official_delegate_ids,
)


def expand_delegate_id_names(
    official_ids: pd.DataFrame,
    aliases: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """One CSV row per searchable name variant sharing the same delegate ID."""
    if official_ids.empty:
        return pd.DataFrame(columns=["name", "delegate_id"])

    alias_frame = aliases if aliases is not None else load_name_aliases(DEFAULT_ALIASES_PATH)
    alias_by_key: dict[str, set[str]] = {}
    if not alias_frame.empty:
        for _, row in alias_frame.iterrows():
            person_key = str(row.get("person_key") or "").strip()
            variant = str(row.get("name_variant") or "").strip()
            if person_key and variant:
                alias_by_key.setdefault(person_key, set()).add(variant)

    rows: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for _, person in official_ids.iterrows():
        delegate_id = str(person.get("official_delegate_id") or "").strip()
        if not delegate_id:
            continue
        person_key = str(person.get("person_key") or "").strip()
        names = {str(person.get("canonical_name") or "").strip()}
        names.update(alias_by_key.get(person_key, set()))
        names = {name for name in names if name}
        for name in sorted(names, key=str.casefold):
            key = (name.casefold(), delegate_id)
            if key in seen:
                continue
            seen.add(key)
            rows.append({"name": name, "delegate_id": delegate_id})

    return pd.DataFrame(rows, columns=["name", "delegate_id"])


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--input",
        type=Path,
        default=DEFAULT_OFFICIAL_IDS_PATH,
        help="Local person_registry_official_ids.csv (gitignored)",
    )
    parser.add_argument(
        "--aliases",
        type=Path,
        default=PERSON_ALIASES_CSV,
        help="Person name aliases used to add searchable name variants",
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

    aliases = load_name_aliases(args.aliases) if args.aliases.exists() else pd.DataFrame()
    output = expand_delegate_id_names(official_ids, aliases=aliases)
    if args.sample > 0:
        output = output.head(args.sample)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    output.to_csv(args.output, index=False)
    print(f"Wrote {len(output):,} rows to {args.output}")


if __name__ == "__main__":
    main()
