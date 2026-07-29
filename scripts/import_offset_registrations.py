#!/usr/bin/env python3
"""Import or restore offset registrations from JSON.

Accepts either shape:

* a backup snapshot from `scripts/backup_offsets.py`, whose rows keep their
  original timestamp, status, pool, and affiliation bucket;
* a bare list of attendee ids (the older `data/offset-registrations.json`),
  which are inserted as published registrations stamped now.

Only missing ids are inserted, so this tops a database up rather than
overwriting it.

    python scripts/import_offset_registrations.py backups/offsets-20260801T030000Z.json
"""

from __future__ import annotations

import json
import sqlite3
import sys
from datetime import UTC, datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = PROJECT_ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from offset_api import (  # noqa: E402
    ATTENDEE_ID_RE,
    STATUS_PUBLISHED,
    _add_registration,
    _db_path,
    _init_db,
)

DEFAULT_JSON = PROJECT_ROOT / "data" / "offset-registrations.json"


def _restore_rows(rows: list[dict]) -> int:
    """Insert full rows, keeping the fields that make the audit trail usable."""
    now = datetime.now(UTC).isoformat(timespec="seconds")
    created = 0
    conn = sqlite3.connect(_db_path())
    try:
        for row in rows:
            attendee_id = str(row.get("attendee_id", "")).strip()
            if not ATTENDEE_ID_RE.fullmatch(attendee_id):
                print(f"  skipped malformed id {attendee_id!r}")
                continue
            cursor = conn.execute(
                """
                INSERT OR IGNORE INTO registrations
                    (attendee_id, name, created_at, source, client_hint, revoked,
                     affiliation_key, pool, status)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    attendee_id,
                    row.get("name"),
                    row.get("created_at") or now,
                    row.get("source") or "restore",
                    row.get("client_hint"),
                    row.get("revoked") or 0,
                    row.get("affiliation_key"),
                    row.get("pool"),
                    row.get("status") or STATUS_PUBLISHED,
                ),
            )
            if cursor.rowcount == 1:
                created += 1
                conn.execute(
                    """
                    INSERT INTO registration_events
                        (attendee_id, event, name, source, client_hint, created_at)
                    VALUES (?, 'restored', ?, 'restore', NULL, ?)
                    """,
                    (attendee_id, row.get("name"), now),
                )
        conn.commit()
    finally:
        conn.close()
    return created


def main() -> None:
    path = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_JSON
    if not path.exists():
        raise SystemExit(f"File not found: {path}")

    payload = json.loads(path.read_text(encoding="utf-8"))
    entries = payload if isinstance(payload, list) else payload.get("registrations", [])
    if not isinstance(entries, list):
        raise SystemExit("Expected 'registrations' to be a list.")

    _init_db()

    rows = [entry for entry in entries if isinstance(entry, dict)]
    ids = [str(entry).strip() for entry in entries if not isinstance(entry, dict) and str(entry).strip()]

    created = _restore_rows(rows) if rows else 0
    for attendee_id in ids:
        if _add_registration(attendee_id, None, source="import"):
            created += 1

    print(f"Imported {created} new registration(s) from {path} ({len(rows) + len(ids)} listed).")


if __name__ == "__main__":
    main()
