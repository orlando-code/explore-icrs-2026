#!/usr/bin/env python3
"""Export verified speaker emails for the contact API (server-side only)."""

from __future__ import annotations

import json
import sys
from datetime import UTC, datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.speaker_profiles import DEFAULT_CACHE_PATH, _profile_key, verified_contact_email

DEFAULT_OUTPUT_PATH = PROJECT_ROOT / "backend" / "data" / "contacts.json"


def export_contacts(cache_path: Path = DEFAULT_CACHE_PATH) -> dict[str, str]:
    cache = json.loads(cache_path.read_text(encoding="utf-8"))
    contacts: dict[str, str] = {}
    for key, profile in cache.items():
        email = verified_contact_email(profile)
        if not email:
            continue
        name = str(profile.get("name") or key.split("|", 1)[0]).strip()
        affiliation = str(profile.get("affiliation") or "").strip()
        contacts[_profile_key(name, affiliation)] = email
    return contacts


def main() -> None:
    output_path = DEFAULT_OUTPUT_PATH
    contacts = export_contacts()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "updated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "count": len(contacts),
        "contacts": contacts,
    }
    output_path.write_text(json.dumps(payload, ensure_ascii=True, indent=2) + "\n", encoding="utf-8")
    print(f"Exported {len(contacts)} verified emails to {output_path}")


if __name__ == "__main__":
    main()
