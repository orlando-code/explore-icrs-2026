#!/usr/bin/env python3
"""Back up the offset ledger off the server.

The live database sits on a single Fly volume, so it is one bad deploy or one
volume loss away from gone. This pulls the whole ledger — registrations plus the
audit trail — and writes a timestamped JSON snapshot somewhere else.

Remote (normal use; needs ADMIN_TOKEN set on the service and locally):

    ADMIN_TOKEN=… python scripts/backup_offsets.py \
        --url https://icrs-offset-api.fly.dev/api/admin/export

Local database (e.g. inside the container, or against a copy):

    python scripts/backup_offsets.py --db /data/offsets.db

Backups contain names and caller digests, so the destination must be private.
`backups/` is gitignored; point --dir somewhere backed up itself (an OneDrive or
Dropbox folder, a private repo, an external drive) for the "elsewhere" part.
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
import urllib.error
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DIR = PROJECT_ROOT / "backups"


def fetch_remote(url: str, token: str, timeout: int) -> dict:
    request = urllib.request.Request(url, method="GET")
    request.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            if response.status != 200:
                raise SystemExit(f"Export failed: HTTP {response.status}")
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        detail = error.read().decode("utf-8", "replace")[:200]
        raise SystemExit(f"Export failed: HTTP {error.code} {detail}") from error
    except (urllib.error.URLError, TimeoutError) as error:
        raise SystemExit(f"Could not reach {url}: {error}") from error


def read_local(db_path: Path) -> dict:
    if not db_path.exists():
        raise SystemExit(f"No such database: {db_path}")
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        registrations = [
            dict(row)
            for row in conn.execute("SELECT * FROM registrations ORDER BY created_at ASC")
        ]
        events = [
            dict(row)
            for row in conn.execute("SELECT * FROM registration_events ORDER BY id ASC")
        ]
    finally:
        conn.close()
    return {
        "exported_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "registrations": registrations,
        "events": events,
    }


def prune(directory: Path, keep: int) -> list[Path]:
    if keep <= 0:
        return []
    snapshots = sorted(directory.glob("offsets-*.json"))
    stale = snapshots[:-keep] if len(snapshots) > keep else []
    for path in stale:
        path.unlink()
    return stale


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--url", help="Admin export endpoint")
    source.add_argument("--db", type=Path, help="Path to a SQLite database instead")
    parser.add_argument("--dir", type=Path, default=DEFAULT_DIR, help="Where to write snapshots")
    parser.add_argument("--keep", type=int, default=30, help="How many snapshots to retain (0 = all)")
    parser.add_argument("--timeout", type=int, default=30)
    parser.add_argument(
        "--token-env",
        default="ADMIN_TOKEN",
        help="Environment variable holding the export token",
    )
    args = parser.parse_args()

    if args.url:
        token = os.environ.get(args.token_env, "").strip()
        if not token:
            raise SystemExit(f"{args.token_env} is not set — cannot authenticate the export.")
        payload = fetch_remote(args.url, token, args.timeout)
        origin = args.url
    else:
        payload = read_local(args.db)
        origin = str(args.db)

    registrations = payload.get("registrations", [])
    events = payload.get("events", [])
    if not isinstance(registrations, list) or not isinstance(events, list):
        raise SystemExit("Unexpected export shape — refusing to overwrite a snapshot with it.")

    args.dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    target = args.dir / f"offsets-{stamp}.json"
    # Never overwrite: two runs in the same second must not lose a snapshot.
    suffix = 1
    while target.exists():
        target = args.dir / f"offsets-{stamp}-{suffix}.json"
        suffix += 1
    target.write_text(
        json.dumps(
            {
                "source": origin,
                "backed_up_at": datetime.now(UTC).isoformat(timespec="seconds"),
                **payload,
            },
            ensure_ascii=True,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    published = sum(1 for row in registrations if row.get("status") == "published")
    pending = sum(1 for row in registrations if row.get("status") == "pending")
    revoked = sum(1 for row in registrations if row.get("status") == "revoked")
    print(f"Wrote {target}")
    print(
        f"  {len(registrations)} registration(s): "
        f"{published} published, {pending} pending, {revoked} revoked"
    )
    print(f"  {len(events)} audit event(s)")

    removed = prune(args.dir, args.keep)
    if removed:
        print(f"  pruned {len(removed)} old snapshot(s)")

    if not registrations:
        print("  WARNING: the ledger is empty — check this is expected before trusting it.", file=sys.stderr)


if __name__ == "__main__":
    main()
