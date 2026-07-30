#!/usr/bin/env python3
"""Generate delegate name → 5-digit ID CSV for offset registration.

IDs are deterministic per name (stable across regenerations). The CSV stays
server-side only; visitors must know their ID to register.

    python scripts/generate_delegate_ids_csv.py
    python scripts/generate_delegate_ids_csv.py --limit 25 --output backend/data/delegate_ids.sample.csv
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SOURCE = PROJECT_ROOT / "data" / "delegates.json"
DEFAULT_OUTPUT = PROJECT_ROOT / "backend" / "data" / "delegate_ids.csv"


def stable_delegate_id(name: str, used: set[str]) -> str:
    digest = hashlib.sha256(name.strip().lower().encode("utf-8")).hexdigest()
    candidate = 10_000 + (int(digest[:8], 16) % 90_000)
    while True:
        delegate_id = f"{candidate:05d}"
        if delegate_id not in used:
            used.add(delegate_id)
            return delegate_id
        candidate = 10_000 + ((candidate - 10_000 + 1) % 90_000)


def load_names(source: Path, speakers_only: bool) -> list[str]:
    payload = json.loads(source.read_text(encoding="utf-8"))
    delegates = payload.get("delegates") if isinstance(payload, dict) else payload
    names: list[str] = []
    seen: set[str] = set()
    for row in delegates:
        if speakers_only and not row.get("is_speaker"):
            continue
        name = str(row.get("full_name") or "").strip()
        if not name:
            continue
        key = name.lower()
        if key in seen:
            continue
        seen.add(key)
        names.append(name)
    return sorted(names, key=lambda value: value.lower())


def write_csv(names: list[str], output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    used: set[str] = set()
    with output.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["name", "delegate_id"])
        writer.writeheader()
        for name in names:
            writer.writerow({"name": name, "delegate_id": stable_delegate_id(name, used)})


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--limit", type=int, default=0, help="Cap rows (0 = all speakers)")
    parser.add_argument(
        "--all-delegates",
        action="store_true",
        help="Include non-speaking delegates (default: speakers only)",
    )
    parser.add_argument(
        "--include-names",
        nargs="*",
        default=[],
        help="Always include these names (useful for sample CSVs)",
    )
    args = parser.parse_args()

    all_names = load_names(args.source, speakers_only=not args.all_delegates)
    include = {name.strip().lower() for name in args.include_names if name.strip()}
    included = [name for name in all_names if name.lower() in include]
    remaining = [name for name in all_names if name.lower() not in include]
    names = included
    if args.limit > 0:
        names.extend(remaining[: max(0, args.limit - len(names))])
    else:
        names.extend(remaining)
    names = sorted(set(names), key=lambda value: value.lower())
    write_csv(names, args.output)
    print(f"Wrote {len(names)} rows to {args.output}")


if __name__ == "__main__":
    main()
