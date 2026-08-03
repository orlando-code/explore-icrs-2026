#!/usr/bin/env python3
"""Sanitize and export speaker profiles from cache to js/speaker-profiles.js."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.plot_utils import speakers_by_profile_connections
from src.programme import load_talks
from src.speaker_profiles import _profile_key, public_profile_for_export

DEFAULT_CACHE_PATH = PROJECT_ROOT / "data" / "speaker_profiles_cache.json"
DEFAULT_OUTPUT_PATH = PROJECT_ROOT / "js" / "speaker-profiles.js"


def main() -> None:
    cache_path = DEFAULT_CACHE_PATH
    output_path = DEFAULT_OUTPUT_PATH
    cache = json.loads(cache_path.read_text(encoding="utf-8"))
    text = output_path.read_text(encoding="utf-8")
    match = re.match(
        r"(/\*\*.*?\*/\nexport const SPEAKER_PROFILES = )(.*)(;\n?)$",
        text,
        re.DOTALL,
    )
    if not match:
        raise SystemExit("Unexpected speaker-profiles.js format")

    talks = load_talks()
    roster = {
        name: (affiliation, role, affiliation_explicit)
        for name, affiliation, role, affiliation_explicit in speakers_by_profile_connections(
            talks
        )
    }

    profiles: dict[str, dict] = {}
    cache_by_name = {entry["name"]: entry for entry in cache.values()}
    verified = 0
    with_email = 0

    for name, (affiliation, role, affiliation_explicit) in roster.items():
        src = cache.get(_profile_key(name, affiliation)) or cache_by_name.get(name)
        if not src:
            continue
        cleaned = public_profile_for_export(src)
        cleaned["profile_role"] = role
        cleaned["affiliation_explicit"] = affiliation_explicit
        if src.get("verified"):
            verified += 1
        if cleaned.get("has_verified_email"):
            with_email += 1
        profiles[name] = cleaned

    output_path.write_text(
        match.group(1) + json.dumps(profiles, ensure_ascii=True, indent=2) + match.group(3),
        encoding="utf-8",
    )
    print(
        f"Exported {len(profiles)} public profiles "
        f"({verified} verified, {with_email} with verified email, no emails in JS)"
    )


if __name__ == "__main__":
    main()
