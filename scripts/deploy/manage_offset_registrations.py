#!/usr/bin/env python3
"""Inspect, hold, and withdraw offset registrations.

Rows are never deleted. Every registration carries a status — published,
pending (held for review), or revoked — and every change appends an audit
event, so a suspect batch can be excluded without losing the record that it
happened. Any command that changes the database snapshots it first.

    python scripts/deploy/manage_offset_registrations.py stats
    python scripts/deploy/manage_offset_registrations.py list --status pending
    python scripts/deploy/manage_offset_registrations.py history offset-bdc15009
    python scripts/deploy/manage_offset_registrations.py approve offset-bdc15009
    python scripts/deploy/manage_offset_registrations.py revoke offset-bdc15009 --reason spam
    python scripts/deploy/manage_offset_registrations.py revoke-matching --client 49e8159 --reason "scripted burst"
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
from collections import Counter
from datetime import UTC, datetime, timedelta
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = PROJECT_ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from offset_api import (  # noqa: E402
    STATUS_PENDING,
    STATUS_PUBLISHED,
    STATUS_REVOKED,
    _db_path,
    _init_db,
)

STATUSES = (STATUS_PUBLISHED, STATUS_PENDING, STATUS_REVOKED)


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(_db_path())
    conn.row_factory = sqlite3.Row
    return conn


def _snapshot(label: str) -> Path:
    """Copy the database before a mutating command, using SQLite's own backup."""
    source = Path(_db_path())
    target_dir = source.parent / "snapshots"
    target_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    target = target_dir / f"{source.stem}-{stamp}-{label}.db"
    # Never overwrite: two commands in the same second must both leave a copy.
    suffix = 1
    while target.exists():
        target = target_dir / f"{source.stem}-{stamp}-{label}-{suffix}.db"
        suffix += 1

    with sqlite3.connect(source) as src, sqlite3.connect(target) as dest:
        src.backup(dest)
    return target


def _log_event(conn: sqlite3.Connection, attendee_id: str, event: str, reason: str) -> None:
    conn.execute(
        """
        INSERT INTO registration_events
            (attendee_id, event, name, source, client_hint, created_at)
        VALUES (?, ?, NULL, ?, NULL, ?)
        """,
        (attendee_id, event, reason or "manual", datetime.now(UTC).isoformat(timespec="seconds")),
    )


def _describe(row: sqlite3.Row) -> str:
    return (
        f"{row['attendee_id']}  {row['created_at']}  {row['status']:<9} "
        f"pool={(row['pool'] or '-'):<9} source={row['source'] or '-'}  "
        f"client={row['client_hint'] or '-'}  name={row['name'] or '-'}"
    )


def cmd_list(args: argparse.Namespace) -> None:
    query = "SELECT * FROM registrations"
    params: tuple = ()
    if args.status != "all":
        query += " WHERE status = ?"
        params = (args.status,)
    query += " ORDER BY created_at ASC"

    with _connect() as conn:
        rows = conn.execute(query, params).fetchall()

    if not rows:
        print(f"No registrations with status {args.status}.")
        return
    for row in rows:
        print(_describe(row))
    print(f"\n{len(rows)} registration(s).")


def cmd_stats(args: argparse.Namespace) -> None:
    with _connect() as conn:
        by_status = Counter(
            {row["status"]: row["tally"] for row in conn.execute(
                "SELECT status, COUNT(*) AS tally FROM registrations GROUP BY status"
            )}
        )
        cutoff = (datetime.now(UTC) - timedelta(hours=args.hours)).isoformat(timespec="seconds")
        recent = conn.execute(
            """
            SELECT attendee_id, created_at, status, client_hint
            FROM registrations
            WHERE created_at >= ?
            ORDER BY created_at ASC
            """,
            (cutoff,),
        ).fetchall()

    print("Status:")
    for status in STATUSES:
        print(f"  {status:<10} {by_status.get(status, 0)}")
    unknown = set(by_status) - set(STATUSES)
    for status in sorted(unknown):
        print(f"  {status:<10} {by_status[status]}  (unrecognised)")
    print(f"  {'total':<10} {sum(by_status.values())}")

    print(f"\nLast {args.hours}h: {len(recent)} registration(s)")
    if not recent:
        return

    per_hour = Counter(row["created_at"][:13] for row in recent)
    print("  by hour (UTC):")
    for hour, tally in sorted(per_hour.items()):
        print(f"    {hour}:00  {'#' * min(tally, 60)} {tally}")

    per_client = Counter(row["client_hint"] or "-" for row in recent)
    busiest = per_client.most_common(5)
    if busiest and busiest[0][1] > 1:
        print("  busiest callers:")
        for hint, tally in busiest:
            print(f"    {hint}  {tally}")


def cmd_history(args: argparse.Namespace) -> None:
    with _connect() as conn:
        rows = conn.execute(
            """
            SELECT event, name, source, client_hint, created_at
            FROM registration_events
            WHERE attendee_id = ?
            ORDER BY id ASC
            """,
            (args.attendee_id,),
        ).fetchall()

    if not rows:
        print(f"No events for {args.attendee_id}.")
        return
    for row in rows:
        print(
            f"{row['created_at']}  {row['event']:<9} source={row['source'] or '-'}  "
            f"client={row['client_hint'] or '-'}  name={row['name'] or '-'}"
        )


def _set_status(attendee_ids: list[str], status: str, event: str, reason: str) -> int:
    snapshot = _snapshot(event)
    changed = 0
    with _connect() as conn:
        for attendee_id in attendee_ids:
            cursor = conn.execute(
                "UPDATE registrations SET status = ? WHERE attendee_id = ? AND status != ?",
                (status, attendee_id, status),
            )
            if cursor.rowcount == 1:
                _log_event(conn, attendee_id, event, reason)
                changed += 1
            else:
                print(f"  skipped {attendee_id} (missing, or already {status})")
    print(f"Snapshot: {snapshot}")
    return changed


def cmd_approve(args: argparse.Namespace) -> None:
    changed = _set_status(args.attendee_ids, STATUS_PUBLISHED, "approved", args.reason)
    print(f"Published {changed} registration(s).")


def cmd_revoke(args: argparse.Namespace) -> None:
    changed = _set_status(args.attendee_ids, STATUS_REVOKED, "revoked", args.reason)
    print(f"Revoked {changed} registration(s).")


def cmd_hold(args: argparse.Namespace) -> None:
    changed = _set_status(args.attendee_ids, STATUS_PENDING, "held", args.reason)
    print(f"Held {changed} registration(s) for review.")


def cmd_revoke_matching(args: argparse.Namespace) -> None:
    """Bulk withdrawal for a burst, selected by caller digest and/or time window."""
    if not any([args.client, args.since, args.until]):
        raise SystemExit("Give at least one of --client, --since, --until.")

    clauses = ["status != ?"]
    params: list = [STATUS_REVOKED]
    if args.client:
        clauses.append("client_hint LIKE ?")
        params.append(f"{args.client}%")
    if args.since:
        clauses.append("created_at >= ?")
        params.append(args.since)
    if args.until:
        clauses.append("created_at <= ?")
        params.append(args.until)

    with _connect() as conn:
        rows = conn.execute(
            f"SELECT * FROM registrations WHERE {' AND '.join(clauses)} ORDER BY created_at ASC",
            params,
        ).fetchall()

    if not rows:
        print("Nothing matched.")
        return

    for row in rows:
        print(_describe(row))
    print(f"\n{len(rows)} registration(s) matched.")
    if not args.yes:
        print("Re-run with --yes to revoke them.")
        return

    changed = _set_status(
        [row["attendee_id"] for row in rows], STATUS_REVOKED, "revoked", args.reason
    )
    print(f"Revoked {changed} registration(s).")


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    list_parser = subparsers.add_parser("list", help="List registrations")
    list_parser.add_argument(
        "--status", choices=[*STATUSES, "all"], default=STATUS_PUBLISHED
    )
    list_parser.set_defaults(func=cmd_list)

    stats_parser = subparsers.add_parser("stats", help="Counts by status and recent rate")
    stats_parser.add_argument("--hours", type=int, default=24)
    stats_parser.set_defaults(func=cmd_stats)

    history_parser = subparsers.add_parser("history", help="Audit trail for one id")
    history_parser.add_argument("attendee_id")
    history_parser.set_defaults(func=cmd_history)

    for name, help_text, func in (
        ("approve", "Publish held registrations", cmd_approve),
        ("revoke", "Withdraw registrations from the published totals", cmd_revoke),
        ("hold", "Move registrations back into the review queue", cmd_hold),
    ):
        sub = subparsers.add_parser(name, help=help_text)
        sub.add_argument("attendee_ids", nargs="+")
        sub.add_argument("--reason", default="manual")
        sub.set_defaults(func=func)

    bulk_parser = subparsers.add_parser(
        "revoke-matching", help="Withdraw a burst by caller digest and/or time window"
    )
    bulk_parser.add_argument("--client", help="Client hint prefix, as shown by stats/list")
    bulk_parser.add_argument("--since", help="ISO timestamp, inclusive")
    bulk_parser.add_argument("--until", help="ISO timestamp, inclusive")
    bulk_parser.add_argument("--reason", default="bulk revoke")
    bulk_parser.add_argument("--yes", action="store_true", help="Apply instead of previewing")
    bulk_parser.set_defaults(func=cmd_revoke_matching)

    args = parser.parse_args()
    _init_db()
    args.func(args)


if __name__ == "__main__":
    main()
