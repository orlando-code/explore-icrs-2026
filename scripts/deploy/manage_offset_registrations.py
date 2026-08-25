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
    python scripts/deploy/manage_offset_registrations.py lookup-privacy 19 Gal
    python scripts/deploy/manage_offset_registrations.py register-privacy 19 Gal --yes
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
from collections import Counter
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = PROJECT_ROOT / "backend"
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from offset_api import (  # noqa: E402
    STATUS_PENDING,
    STATUS_PUBLISHED,
    STATUS_REVOKED,
    _add_registration,
    _db_path,
    _init_db,
)

STATUSES = (STATUS_PUBLISHED, STATUS_PENDING, STATUS_REVOKED)

PROJECT_DATA = PROJECT_ROOT / "data"


def _fold_person_name(value: str) -> str:
    from src.sources.delegates import normalize_person_name

    return normalize_person_name(str(value or ""))


def _load_check_in_source(path: Path | None = None) -> pd.DataFrame:
    from src.registry.check_in_attendance import (
        DEFAULT_CHECK_IN_SOURCE_PATH,
        apply_check_in_overrides,
        _normalize_check_in_country,
    )

    check_in_path = path or DEFAULT_CHECK_IN_SOURCE_PATH
    frame = pd.read_csv(check_in_path, dtype={"ID": "Int64"}, encoding="latin-1")
    frame.columns = frame.columns.str.strip().str.lower()
    frame.rename(columns={"organsation": "organisation"}, inplace=True)
    if "id" in frame.columns and "ID" not in frame.columns:
        frame = frame.rename(columns={"id": "ID"})
    for column in ("first name", "organisation", "country"):
        if column not in frame.columns:
            frame[column] = ""
    frame = apply_check_in_overrides(frame)
    if "country" in frame.columns:
        frame["country"] = frame["country"].map(_normalize_check_in_country)
    return frame


def _privacy_check_in_ids() -> frozenset[int]:
    from src.data_paths import PERSON_OFFICIAL_IDS_CSV
    from src.registry.check_in_attendance import _registered_official_delegate_ids

    official_path = PERSON_OFFICIAL_IDS_CSV
    if not official_path.exists():
        return frozenset()
    official = pd.read_csv(official_path, dtype=str).fillna("")
    return _registered_official_delegate_ids(official)


def _resolve_privacy_delegate(
    check_in_id: int,
    first_name: str,
    *,
    check_in_path: Path | None = None,
) -> dict[str, str]:
    """Match Innovators check-in row by numeric ID + first name; build pledge fields."""
    from src.data_paths import PERSON_REGISTRY_CSV
    from src.emissions.travel_emissions import _emissions_location_key, _stable_attendee_id
    from src.geocoding.geocode import affiliation_display_name
    from src.registry.affiliation_registry import _make_affiliation
    from src.registry.person_registry import load_person_registry

    if check_in_id <= 0:
        raise SystemExit("Check-in ID must be a positive integer.")

    registered_ids = _privacy_check_in_ids()
    if check_in_id in registered_ids:
        raise SystemExit(
            f"ID {check_in_id} is on the pre-registration delegate list — "
            "they can register via the site with their welcome-email delegate ID."
        )

    frame = _load_check_in_source(check_in_path)
    rows = frame.loc[frame["ID"].eq(check_in_id)]
    if rows.empty:
        raise SystemExit(
            f"No row with ID {check_in_id} in the check-in export "
            f"({check_in_path or 'data/registry/all_delegates_checked_in.csv'})."
        )

    want_name = _fold_person_name(first_name)
    if not want_name:
        raise SystemExit("First name is required.")

    matched = [
        row
        for _, row in rows.iterrows()
        if _fold_person_name(str(row.get("first name") or "")) == want_name
    ]
    if not matched:
        actual = ", ".join(
            sorted({str(row.get("first name") or "").strip() for _, row in rows.iterrows()})
        )
        raise SystemExit(
            f"First name {first_name!r} does not match ID {check_in_id} "
            f"(check-in has: {actual})."
        )
    if len(matched) > 1:
        raise SystemExit(f"Ambiguous: ID {check_in_id} matched multiple first-name rows.")

    row = matched[0]
    display_name = str(row.get("first name") or "").strip()
    organisation = str(row.get("organisation") or "").strip()
    country = str(row.get("country") or "").strip()
    if not organisation and not country:
        raise SystemExit(
            f"Check-in row {check_in_id} has no organisation or country — "
            "add overrides in data/overrides/check_in_overrides.csv and retry."
        )

    affiliation_raw = _make_affiliation(organisation, country)
    affiliation_label = affiliation_display_name(affiliation_raw) or affiliation_raw
    affiliation_key = _emissions_location_key(affiliation_raw)
    if not affiliation_key:
        affiliation_key = _emissions_location_key(affiliation_label)
    if not affiliation_key:
        raise SystemExit(
            f"Could not derive an affiliation map key for {affiliation_label!r}."
        )

    person_key = ""
    if PERSON_REGISTRY_CSV.exists():
        registry = load_person_registry(PERSON_REGISTRY_CSV)
        if "official_delegate_id" in registry.columns:
            reg_rows = registry.loc[
                registry["official_delegate_id"].astype(str).str.strip() == str(check_in_id)
            ]
            if not reg_rows.empty:
                person_key = str(reg_rows.iloc[0].get("person_key") or "").strip()

    attendee_id = _stable_attendee_id(
        display_name,
        person_key=person_key,
        affiliation=affiliation_label,
    )

    return {
        "check_in_id": str(check_in_id),
        "name": display_name,
        "affiliation": affiliation_label,
        "affiliation_key": affiliation_key,
        "person_key": person_key,
        "attendee_id": attendee_id,
        "pool": "delegates",
    }


def _print_privacy_match(match: dict[str, str]) -> None:
    print(f"  check-in ID     {match['check_in_id']}")
    print(f"  name            {match['name']}")
    print(f"  affiliation     {match['affiliation']}")
    print(f"  affiliation_key {match['affiliation_key']}")
    if match.get("person_key"):
        print(f"  person_key      {match['person_key']}")
    print(f"  attendee_id     {match['attendee_id']}")
    print(f"  pool            {match['pool']}")


def cmd_lookup_privacy(args: argparse.Namespace) -> None:
    match = _resolve_privacy_delegate(
        args.id,
        args.first_name,
        check_in_path=Path(args.check_in_csv) if args.check_in_csv else None,
    )
    print("Matched privacy delegate (no database changes):")
    _print_privacy_match(match)


def cmd_list_privacy(args: argparse.Namespace) -> None:
    registered_ids = _privacy_check_in_ids()
    frame = _load_check_in_source(
        Path(args.check_in_csv) if args.check_in_csv else None
    )
    privacy_rows = frame.loc[~frame["ID"].isin(list(registered_ids))].copy()
    if args.first_name:
        want = _fold_person_name(args.first_name)
        privacy_rows = privacy_rows.loc[
            privacy_rows["first name"].map(lambda value: _fold_person_name(str(value))) == want
        ]
    privacy_rows = privacy_rows.sort_values("ID")
    if privacy_rows.empty:
        print("No privacy check-in rows matched.")
        return
    for _, row in privacy_rows.iterrows():
        print(
            f"ID {int(row['ID']):>4}  "
            f"{str(row.get('first name') or '').strip():<20}  "
            f"{str(row.get('organisation') or '').strip()}, "
            f"{str(row.get('country') or '').strip()}"
        )
    print(f"\n{len(privacy_rows)} privacy check-in row(s).")


def cmd_register_privacy(args: argparse.Namespace) -> None:
    match = _resolve_privacy_delegate(
        args.id,
        args.first_name,
        check_in_path=Path(args.check_in_csv) if args.check_in_csv else None,
    )
    status = args.status
    if status not in STATUSES:
        raise SystemExit(f"Unsupported status {status!r}")

    with _connect() as conn:
        existing = conn.execute(
            "SELECT attendee_id, status FROM registrations WHERE attendee_id = ?",
            (match["attendee_id"],),
        ).fetchone()
        if existing and existing["status"] == status and status == STATUS_PUBLISHED:
            print(f"Already published as {match['attendee_id']}.")
            return

    print("Will register privacy delegate pledge:")
    _print_privacy_match(match)
    print(f"  status          {status}")
    if not args.yes:
        print("\nRe-run with --yes to write to the database.")
        return

    snapshot = _snapshot("register-privacy")
    created, reactivated = _add_registration(
        match["attendee_id"],
        match["name"],
        source="cli-privacy",
        client_hint="cli-privacy",
        affiliation_key=match["affiliation_key"],
        pool=match["pool"],
        status=status,
    )
    if created:
        print(f"Snapshot: {snapshot}")
        print(f"Registered {match['attendee_id']} ({status}).")
    elif reactivated:
        print(f"Snapshot: {snapshot}")
        print(f"Reactivated {match['attendee_id']} from revoked ({status}).")
    else:
        print(f"No change — {match['attendee_id']} already active with this identity.")


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

    lookup_privacy = subparsers.add_parser(
        "lookup-privacy",
        help="Preview a privacy delegate match from Innovators check-in (no DB writes)",
    )
    lookup_privacy.add_argument("id", type=int, help="Innovators check-in ID from CSV")
    lookup_privacy.add_argument("first_name", help="First name (must match check-in export)")
    lookup_privacy.add_argument(
        "--check-in-csv",
        help="Override path (default: data/registry/all_delegates_checked_in.csv)",
    )
    lookup_privacy.set_defaults(func=cmd_lookup_privacy)

    list_privacy = subparsers.add_parser(
        "list-privacy",
        help="List check-in rows not on the pre-registration delegate ID list",
    )
    list_privacy.add_argument(
        "--first-name",
        help="Filter to one folded first name",
    )
    list_privacy.add_argument(
        "--check-in-csv",
        help="Override path (default: data/registry/all_delegates_checked_in.csv)",
    )
    list_privacy.set_defaults(func=cmd_list_privacy)

    register_privacy = subparsers.add_parser(
        "register-privacy",
        help="Register a privacy delegate pledge by check-in ID + first name",
    )
    register_privacy.add_argument("id", type=int, help="Innovators check-in ID from CSV")
    register_privacy.add_argument("first_name", help="First name (must match check-in export)")
    register_privacy.add_argument(
        "--status",
        choices=STATUSES,
        default=STATUS_PUBLISHED,
        help="published counts on the map; pending holds for review",
    )
    register_privacy.add_argument(
        "--check-in-csv",
        help="Override path (default: data/registry/all_delegates_checked_in.csv)",
    )
    register_privacy.add_argument(
        "--yes",
        action="store_true",
        help="Write to OFFSET_DB_PATH (otherwise preview only)",
    )
    register_privacy.set_defaults(func=cmd_register_privacy)

    args = parser.parse_args()
    _init_db()
    args.func(args)


if __name__ == "__main__":
    main()
