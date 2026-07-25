#!/usr/bin/env python3
"""Import attendee ids from data/offset-registrations.json into the offset API database."""

from __future__ import annotations

import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = PROJECT_ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from offset_api import _add_registration, _init_db  # noqa: E402

DEFAULT_JSON = PROJECT_ROOT / "data" / "offset-registrations.json"


def main() -> None:
    path = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_JSON
    if not path.exists():
        raise SystemExit(f"File not found: {path}")

    payload = json.loads(path.read_text(encoding="utf-8"))
    ids = payload if isinstance(payload, list) else payload.get("registrations", [])
    ids = [str(item).strip() for item in ids if str(item).strip()]

    _init_db()
    created = 0
    for attendee_id in ids:
        if _add_registration(attendee_id, None):
            created += 1

    print(f"Imported {created} new registration(s) from {path} ({len(ids)} listed).")


if __name__ == "__main__":
    main()
