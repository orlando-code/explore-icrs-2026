#!/usr/bin/env python3
"""Audit which delegates appear on the map and why others do not."""

from __future__ import annotations

import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.affiliation_geocodes import attach_affiliation_geocodes
from src.delegates import (
    combined_attendee_talks,
    delegate_list_groups,
    delegate_person_key,
    geocoded_delegate_list,
    load_delegates,
)
from src.geocode import affiliation_display_name, canonical_affiliation_key
from src.map_exclusions import is_map_excluded, load_map_exclusions
from src.plot_utils import _affiliation_location_records
from src.programme import load_talks

LOCATIONS_JS = PROJECT_ROOT / "js" / "locations.js"


def _load_site_location_speakers() -> dict[str, set[str]]:
    """Speaker person_keys on exported map pins (before client-side delegate merge)."""
    text = LOCATIONS_JS.read_text(encoding="utf-8")
    payload = json.loads(text.split("export const SITE_DATA = ", 1)[1].rstrip().rstrip(";"))
    by_affiliation: dict[str, set[str]] = {}
    for location in payload.get("locations", []):
        aff = str(location.get("affiliation") or "").strip()
        keys: set[str] = set()
        for speaker in location.get("speaker_details") or []:
            name = str(speaker.get("name") or "").strip()
            if name:
                keys.add(delegate_person_key(name))
        by_affiliation[aff] = keys
    return by_affiliation


def _speaker_keys_on_pins(by_affiliation: dict[str, set[str]]) -> set[str]:
    keys: set[str] = set()
    for speaker_keys in by_affiliation.values():
        keys.update(speaker_keys)
    return keys


def _delegate_index_keys() -> dict[str, list[dict]]:
    groups = delegate_list_groups()
    index: dict[str, list[dict]] = defaultdict(list)
    for group in groups:
        key = canonical_affiliation_key(group["affiliation"]).casefold()
        index[key].extend(group["delegates"])
    return index


def _geocode_status(geo_row) -> str:
    if geo_row is None:
        return "no_geocode"
    lat = geo_row.get("latitude")
    lon = geo_row.get("longitude")
    if lat is None or lon is None or (str(lat) == "nan" and str(lon) == "nan"):
        return "no_coords"
    return "geocoded"


def main() -> None:
    delegates = load_delegates()
    map_exclusions = load_map_exclusions()
    talks = load_talks()
    talks_geo = attach_affiliation_geocodes(talks)
    talks_geo = combined_attendee_talks(
        talks_geo,
        include_non_speakers=True,
        delegates=delegates,
    )
    site_pins = _affiliation_location_records(talks_geo)
    site_by_aff = _load_site_location_speakers()
    on_pin_keys = _speaker_keys_on_pins(site_by_aff)

    geo_df = geocoded_delegate_list(delegates)
    geo_by_name = {
        str(row["presenter"]).strip(): row
        for _, row in geo_df.iterrows()
        if str(row.get("presenter") or "").strip()
    }

    delegate_groups = delegate_list_groups()
    group_by_key = {
        canonical_affiliation_key(g["affiliation"]).casefold(): g for g in delegate_groups
    }
    delegate_index = _delegate_index_keys()

    # Affiliations with exported map pins.
    pin_aff_keys = {
        canonical_affiliation_key(loc["affiliation"]).casefold() for loc in site_pins
    }

    rows: list[dict] = []
    reason_counts: Counter[str] = Counter()

    for _, row in delegates.iterrows():
        name = str(row.get("full_name") or "").strip()
        if not name:
            reason_counts["missing_name"] += 1
            continue

        person_key = delegate_person_key(name)
        is_speaker = bool(row.get("is_speaker"))
        affiliation = str(row.get("affiliation") or row.get("organisation") or "").strip()
        display = affiliation_display_name(affiliation) or affiliation
        aff_key = canonical_affiliation_key(affiliation).casefold()
        geo_row = geo_by_name.get(name)
        geocode_status = _geocode_status(geo_row.to_dict() if geo_row is not None else None)

        on_talk_pin = person_key in on_pin_keys
        in_delegate_group = aff_key in group_by_key
        has_pin_for_affiliation = aff_key in pin_aff_keys

        if is_map_excluded(name, set(map_exclusions.names)):
            reason = "map_excluded_name"
        elif not affiliation:
            reason = "missing_affiliation"
        elif not in_delegate_group:
            reason = "excluded_from_delegate_groups"
        elif on_talk_pin:
            reason = "on_map_via_talks"
        elif is_speaker and not on_talk_pin:
            if geocode_status != "geocoded":
                reason = "speaker_no_geocode"
            elif not has_pin_for_affiliation:
                reason = "speaker_geocoded_but_affiliation_no_pin"
            else:
                reason = "speaker_geocoded_aff_has_pin_but_person_missing"
        elif geocode_status != "geocoded":
            reason = "delegate_no_geocode"
        elif not has_pin_for_affiliation:
            reason = "delegate_geocoded_but_affiliation_no_pin"
        elif not on_talk_pin:
            reason = "delegate_needs_client_merge"
        else:
            reason = "mapped"

        reason_counts[reason] += 1
        rows.append(
            {
                "name": name,
                "person_key": person_key,
                "is_speaker": is_speaker,
                "country": str(row.get("country") or ""),
                "affiliation": affiliation,
                "display_affiliation": display,
                "aff_key": aff_key,
                "geocode_status": geocode_status,
                "on_talk_pin": on_talk_pin,
                "has_pin_for_affiliation": has_pin_for_affiliation,
                "reason": reason,
            }
        )

    total = len(rows)
    mapped_talk = sum(1 for r in rows if r["reason"] == "on_map_via_talks")
    client_merge = sum(1 for r in rows if r["reason"] == "delegate_needs_client_merge")
    unmapped = total - mapped_talk - client_merge

    print("=" * 72)
    print("DELEGATE MAP COVERAGE AUDIT")
    print("=" * 72)
    print(f"Total delegates in list: {total:,}")
    print(f"On map via talks export (server-side pins): {mapped_talk:,}")
    print(f"Would merge client-side IF affiliation pin exists + toggle on: {client_merge:,}")
    print(f"NOT on map (even with delegate toggle): {unmapped:,}")
    print()
    print("Reason breakdown:")
    for reason, count in reason_counts.most_common():
        print(f"  {reason:45} {count:5}")
    print()

    # Réunion spotlight
    reunion = [r for r in rows if "réunion" in r["country"].lower() or "reunion" in r["country"].lower()]
    if reunion:
        print("-" * 72)
        print(f"RÉUNION DELEGATES ({len(reunion)}):")
        for r in reunion:
            print(
                f"  {r['name']:30} | speaker={r['is_speaker']} | "
                f"{r['display_affiliation']:25} | {r['reason']}"
            )
        print()

    # Sample unmapped
    print("-" * 72)
    print("UNMAPPED DELEGATES (sample up to 40):")
    unmapped_rows = [r for r in rows if r["reason"] not in {"on_map_via_talks", "delegate_needs_client_merge"}]
    by_reason: dict[str, list[dict]] = defaultdict(list)
    for r in unmapped_rows:
        by_reason[r["reason"]].append(r)

    shown = 0
    for reason in sorted(by_reason, key=lambda k: (-len(by_reason[k]), k)):
        group = by_reason[reason]
        print(f"\n[{reason}] ({len(group)} total)")
        for r in group[:8]:
            print(
                f"  {r['name']:32} | {r['country']:18} | "
                f"{r['display_affiliation'][:40]:40} | geo={r['geocode_status']}"
            )
        shown += min(8, len(group))
        if shown >= 40:
            break

    # Affiliations with geocoded delegates but no pin
    print()
    print("-" * 72)
    print("AFFILIATIONS: geocoded delegates exist, but NO talk-based map pin:")
    missing_pin_affs: dict[str, list[str]] = defaultdict(list)
    for r in rows:
        if r["reason"] in {"delegate_geocoded_but_affiliation_no_pin", "speaker_geocoded_but_affiliation_no_pin"}:
            missing_pin_affs[r["display_affiliation"]].append(r["name"])
    for aff, names in sorted(missing_pin_affs.items(), key=lambda kv: -len(kv[1]))[:25]:
        print(f"  {aff} ({len(names)} delegates): {', '.join(names[:4])}{'…' if len(names) > 4 else ''}")

    # Write CSV for user
    out = PROJECT_ROOT / "data" / "delegate_map_coverage_audit.csv"
    import pandas as pd

    pd.DataFrame(rows).to_csv(out, index=False)
    print()
    print(f"Full audit written to {out.relative_to(PROJECT_ROOT)}")


if __name__ == "__main__":
    main()
