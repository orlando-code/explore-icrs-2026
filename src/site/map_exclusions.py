"""People and affiliations excluded from map views (main map and emissions map).

Network, talks, and emissions totals in exported JSON can still include these
unless the emissions export applies filter_emissions_pool().
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd

from src.sources.delegates import normalize_person_name
from src.geocoding.geocode import canonical_affiliation_key
from src.data_paths import MAP_EXCLUDED_NAMES_JSON, MAP_EXCLUDED_NAMES_TXT

DEFAULT_MAP_EXCLUSIONS_PATH = MAP_EXCLUDED_NAMES_TXT
DEFAULT_MAP_EXCLUSIONS_JSON_PATH = MAP_EXCLUDED_NAMES_JSON
DEFAULT_MAP_EXCLUSIONS_JS_PATH = Path("js/map-excluded-names.js")


@dataclass(frozen=True)
class MapExclusions:
    names: frozenset[str]
    affiliations: frozenset[str]


def _affiliation_key(affiliation: str) -> str:
    return canonical_affiliation_key(affiliation).casefold()


def _parse_exclusion_line(line: str, names: set[str], affiliations: set[str]) -> None:
    cleaned = line.strip()
    if not cleaned or cleaned.startswith("#"):
        return
    if cleaned.startswith("@"):
        affiliation = cleaned[1:].strip()
        if affiliation:
            affiliations.add(_affiliation_key(affiliation))
        return
    names.add(normalize_person_name(cleaned))


def load_map_exclusions(
    path: Path | str = DEFAULT_MAP_EXCLUSIONS_PATH,
    *,
    json_path: Path | str = DEFAULT_MAP_EXCLUSIONS_JSON_PATH,
) -> MapExclusions:
    """Return normalized person names and affiliation keys to omit from the map."""
    names: set[str] = set()
    affiliations: set[str] = set()

    txt_path = Path(path)
    if txt_path.exists():
        for line in txt_path.read_text(encoding="utf-8").splitlines():
            _parse_exclusion_line(line, names, affiliations)

    json_file = Path(json_path)
    if json_file.exists():
        payload = json.loads(json_file.read_text(encoding="utf-8"))
        if isinstance(payload, list):
            for item in payload:
                if isinstance(item, str):
                    _parse_exclusion_line(item, names, affiliations)
                elif isinstance(item, dict):
                    for name in item.get("names", []):
                        _parse_exclusion_line(str(name), names, affiliations)
                    for affiliation in item.get("affiliations", []):
                        _parse_exclusion_line(f"@{affiliation}", names, affiliations)
        elif isinstance(payload, dict):
            for name in payload.get("names", []):
                _parse_exclusion_line(str(name), names, affiliations)
            for affiliation in payload.get("affiliations", []):
                _parse_exclusion_line(f"@{affiliation}", names, affiliations)

    return MapExclusions(names=frozenset(names), affiliations=frozenset(affiliations))


def load_map_excluded_names(
    path: Path | str = DEFAULT_MAP_EXCLUSIONS_PATH,
    *,
    json_path: Path | str = DEFAULT_MAP_EXCLUSIONS_JSON_PATH,
) -> set[str]:
    return set(load_map_exclusions(path, json_path=json_path).names)


def is_map_excluded(name: str, excluded: set[str] | None = None) -> bool:
    if not name:
        return False
    norms = excluded if excluded is not None else load_map_excluded_names()
    return normalize_person_name(name) in norms


def is_map_excluded_affiliation(
    affiliation: str, excluded: set[str] | None = None
) -> bool:
    if not affiliation:
        return False
    keys = excluded if excluded is not None else load_map_exclusions().affiliations
    return _affiliation_key(affiliation) in keys


def map_talks_for_export(
    talks: pd.DataFrame,
    *,
    exclusions: MapExclusions | None = None,
    excluded: set[str] | None = None,
    presenter_col: str = "presenter",
    affiliation_col: str = "affiliation",
) -> pd.DataFrame:
    """Drop talks excluded from the map export (presenter or affiliation)."""
    if exclusions is None:
        exclusions = load_map_exclusions()
    if excluded is not None:
        exclusions = MapExclusions(names=frozenset(excluded), affiliations=exclusions.affiliations)

    if talks.empty:
        return talks

    mask = pd.Series(True, index=talks.index)
    if exclusions.names and presenter_col in talks.columns:
        mask &= talks[presenter_col].map(
            lambda value: pd.isna(value)
            or not is_map_excluded(str(value), set(exclusions.names))
        )
    if exclusions.affiliations and affiliation_col in talks.columns:
        mask &= talks[affiliation_col].map(
            lambda value: pd.isna(value)
            or not is_map_excluded_affiliation(
                str(value), set(exclusions.affiliations)
            )
        )
    return talks.loc[mask].copy()


def filter_emissions_pool(
    pool: dict[str, Any],
    *,
    exclusions: MapExclusions | None = None,
    privacy_person_keys: frozenset[str] | set[str] | None = None,
    preserve_headline: bool = False,
) -> dict[str, Any]:
    """Remove excluded or privacy-restricted people from a display pool."""
    if not pool:
        return pool
    exclusions = exclusions or load_map_exclusions()
    privacy_keys = set(privacy_person_keys or ())
    if not exclusions.names and not exclusions.affiliations and not privacy_keys:
        return pool

    name_set = set(exclusions.names)
    affiliation_set = set(exclusions.affiliations)
    attendees = [
        attendee
        for attendee in pool.get("attendees", [])
        if not (
            privacy_keys
            and str(attendee.get("person_key") or "").strip() in privacy_keys
        )
        and not is_map_excluded(str(attendee.get("name", "")), name_set)
        and not is_map_excluded_affiliation(str(attendee.get("affiliation", "")), affiliation_set)
    ]

    location_by_id = {
        location["id"]: dict(location)
        for location in pool.get("locations", [])
        if location.get("id")
        and not is_map_excluded_affiliation(
            str(location.get("affiliation", "")), affiliation_set
        )
    }

    totals: dict[str, dict[str, float | int]] = {}
    for attendee in attendees:
        location_id = attendee.get("location_id")
        if not location_id or location_id not in location_by_id:
            continue
        bucket = totals.setdefault(location_id, {"co2e_kg": 0.0, "count": 0})
        bucket["co2e_kg"] += float(attendee.get("co2e_kg") or 0)
        bucket["count"] += 1

    locations: list[dict[str, Any]] = []
    for location_id, location in location_by_id.items():
        bucket = totals.get(location_id)
        if not bucket or bucket["count"] <= 0:
            continue
        co2e_kg = round(float(bucket["co2e_kg"]), 1)
        count = int(bucket["count"])
        locations.append(
            {
                **location,
                "co2e_kg": co2e_kg,
                "co2e_low_kg": co2e_kg,
                "co2e_high_kg": co2e_kg,
                "travel_attendees": count,
                "speaker_count": count,
                "co2e_per_speaker_kg": round(co2e_kg / max(count, 1), 1),
            }
        )

    rankings = sorted(locations, key=lambda row: row["co2e_kg"], reverse=True)
    headline = dict(pool.get("meta", {}).get("headline", {}))
    if headline and not preserve_headline:
        total_co2e = round(sum(row["co2e_kg"] for row in locations), 1)
        headline = {
            **headline,
            "co2e_kg": total_co2e,
            "co2e_low_kg": total_co2e,
            "co2e_high_kg": total_co2e,
            "co2e_tonnes": round(total_co2e / 1000, 2),
            "attendees_estimated": len(attendees),
        }

    return {
        **pool,
        "meta": {
            **pool.get("meta", {}),
            "headline": headline,
        },
        "attendees": attendees,
        "locations": locations,
        "rankings": rankings[:30],
    }


def export_map_exclusions_js(
    save_path: str | Path = DEFAULT_MAP_EXCLUSIONS_JS_PATH,
    *,
    exclusions: MapExclusions | None = None,
) -> Path:
    exclusions = exclusions or load_map_exclusions()
    output_path = Path(save_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    body = (
        "/** Generated from data/overrides/map_excluded_names.txt – do not edit by hand. */\n"
        f"export const MAP_EXCLUDED_NAMES = {json.dumps(sorted(exclusions.names), ensure_ascii=True)};\n"
        f"export const MAP_EXCLUDED_AFFILIATION_KEYS = {json.dumps(sorted(exclusions.affiliations), ensure_ascii=True)};\n"
    )
    output_path.write_text(body, encoding="utf-8")
    return output_path
