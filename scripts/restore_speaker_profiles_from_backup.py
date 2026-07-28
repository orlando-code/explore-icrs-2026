#!/usr/bin/env python3
"""Restore speaker profile emails and related fields from a backup cache file.

Use after recovering an older speaker_profiles_cache.json from OneDrive version
history (or any other backup). Merges missing primary emails and verified flags
into the current cache without wiping newer URL edits.

Example:
  cp ~/Downloads/speaker_profiles_cache.json data/speaker_profiles_cache.backup.json
  .venv/bin/python scripts/restore_speaker_profiles_from_backup.py
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from datetime import UTC, datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CACHE_PATH = PROJECT_ROOT / "data" / "speaker_profiles_cache.json"
DEFAULT_BACKUP_PATH = PROJECT_ROOT / "data" / "speaker_profiles_cache.backup.json"


def _email_from_primary(primary: object) -> str | None:
    if not isinstance(primary, dict):
        return None
    if primary.get("type") != "email":
        return None
    label = str(primary.get("label") or "").strip()
    return label if label and "@" in label else None


def merge_profiles(
    current: dict[str, dict],
    backup: dict[str, dict],
    *,
    restore_verified: bool = True,
) -> dict[str, int]:
    stats = {
        "keys_in_backup": len(backup),
        "emails_restored": 0,
        "verified_restored": 0,
        "primary_url_restored": 0,
        "email_score_restored": 0,
        "skipped_had_email": 0,
        "missing_in_current": 0,
    }

    for key, old in backup.items():
        if key not in current:
            stats["missing_in_current"] += 1
            current[key] = dict(old)
            if _email_from_primary(old.get("primary")):
                stats["emails_restored"] += 1
            if old.get("verified") is True:
                stats["verified_restored"] += 1
            continue

        cur = current[key]
        backup_email = _email_from_primary(old.get("primary"))
        current_email = _email_from_primary(cur.get("primary"))

        if backup_email and not current_email:
            cur["primary"] = old.get("primary")
            stats["emails_restored"] += 1
            if old.get("email_score") is not None:
                cur["email_score"] = old["email_score"]
                stats["email_score_restored"] += 1
            if old.get("email_structured") is not None:
                cur["email_structured"] = old["email_structured"]
        elif backup_email and current_email:
            stats["skipped_had_email"] += 1

        if restore_verified and old.get("verified") is True and cur.get("verified") is not True:
            cur["verified"] = True
            stats["verified_restored"] += 1

        backup_primary = old.get("primary") or {}
        cur_primary = cur.get("primary") or {}
        if (
            backup_primary.get("type") != "email"
            and backup_primary.get("url")
            and not cur_primary.get("url")
        ):
            cur["primary"] = backup_primary
            stats["primary_url_restored"] += 1

    return stats


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--cache",
        type=Path,
        default=DEFAULT_CACHE_PATH,
        help="Current cache path",
    )
    parser.add_argument(
        "--backup",
        type=Path,
        default=DEFAULT_BACKUP_PATH,
        help="Backup cache path (older copy with emails)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Report what would be restored without writing",
    )
    args = parser.parse_args()

    if not args.backup.exists():
        raise SystemExit(
            f"Backup not found: {args.backup}\n"
            "Recover an older copy from OneDrive version history first, then save it there."
        )
    if not args.cache.exists():
        raise SystemExit(f"Current cache not found: {args.cache}")

    backup = json.loads(args.backup.read_text(encoding="utf-8"))
    current = json.loads(args.cache.read_text(encoding="utf-8"))
    stats = merge_profiles(current, backup)

    print(f"Backup profiles: {stats['keys_in_backup']}")
    print(f"Emails restored: {stats['emails_restored']}")
    print(f"Verified flags restored: {stats['verified_restored']}")
    print(f"Primary URLs restored: {stats['primary_url_restored']}")
    print(f"Already had email (skipped): {stats['skipped_had_email']}")
    print(f"Profiles only in backup (added): {stats['missing_in_current']}")

    if args.dry_run:
        print("Dry run — no files written.")
        return

    if stats["emails_restored"] == 0 and stats["verified_restored"] == 0:
        print("Nothing to restore. Check that the backup is an older copy with emails.")
        return

    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    pre_restore = args.cache.with_name(f"speaker_profiles_cache.pre-restore.{stamp}.json")
    shutil.copy2(args.cache, pre_restore)
    args.cache.write_text(
        json.dumps(current, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(f"Wrote merged cache to {args.cache}")
    print(f"Saved pre-restore copy to {pre_restore}")


if __name__ == "__main__":
    main()
