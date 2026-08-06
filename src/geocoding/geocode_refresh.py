"""Geocode affiliations from the registry via Google Maps (cached)."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd

from src.geocoding.affiliation_geocodes import load_geocode_source_frames
from src.registry.affiliation_lookup import AffiliationIndex
from src.registry.affiliation_registry import load_affiliation_registry
from src.geocoding.google_geocode import (
    DEFAULT_GOOGLE_CACHE_PATH,
    _load_google_cache,
    _save_google_cache,
    google_geocode_affiliation,
    load_google_maps_api_key,
)
from src.data_paths import (
    AFFILIATION_GEOCODES_CSV,
    AFFILIATION_GEOCODES_MANUAL_CSV,
    AFFILIATION_REGISTRY_CSV,
)
from src.geocoding.capital_coords import resolve_country_anchor_fallback

DEFAULT_GEOCODES_CSV = AFFILIATION_GEOCODES_CSV


@dataclass(frozen=True)
class GeocodeTarget:
    affiliation_key: str
    organisation: str
    country: str

    @property
    def affiliation(self) -> str:
        if self.country:
            return f"{self.organisation}, {self.country}"
        return self.organisation


def _geocoded(status: str) -> bool:
    return str(status or "").strip().lower() in {"ok", "fallback"}


def missing_geocode_targets(
    *,
    plot_on_map_only: bool = False,
) -> list[GeocodeTarget]:
    """Affiliation registry rows that still need coordinates."""
    registry = load_affiliation_registry(AFFILIATION_REGISTRY_CSV)
    if plot_on_map_only:
        registry = registry.loc[
            registry.get("plot_on_map", pd.Series(True))
            .astype(str)
            .str.strip()
            .str.lower()
            .isin({"true", "1", "yes"})
        ]

    targets: list[GeocodeTarget] = []
    for _, row in registry.iterrows():
        if str(row.get("redirect_to_affiliation_key") or "").strip():
            continue
        if _geocoded(str(row.get("geocode_status") or "")):
            continue
        organisation = str(row.get("organisation") or "").strip()
        if not organisation:
            continue
        targets.append(
            GeocodeTarget(
                affiliation_key=str(row["affiliation_key"]),
                organisation=organisation,
                country=str(row.get("country") or "").strip(),
            )
        )
    return targets


def _existing_geocoded_keys() -> set[str]:
    csv = load_geocode_source_frames(
        AFFILIATION_GEOCODES_CSV,
        manual_path=AFFILIATION_GEOCODES_MANUAL_CSV,
    )
    if csv.empty:
        return set()
    ok = csv.loc[csv["status"].eq("OK") & csv["latitude"].notna()]
    index = AffiliationIndex.load()
    keys: set[str] = set()
    for _, row in ok.iterrows():
        key = index.resolve_key(str(row.get("organisation") or ""), str(row.get("country") or ""))
        if key:
            keys.add(key)
    return keys


def refresh_geocodes(
    targets: list[GeocodeTarget] | None = None,
    *,
    output_csv: Path | str = DEFAULT_GEOCODES_CSV,
    cache_path: Path | str = DEFAULT_GOOGLE_CACHE_PATH,
    pause_seconds: float = 0.05,
    skip_existing: bool = True,
    dry_run: bool = False,
) -> pd.DataFrame:
    """Query Google for missing affiliations; append OK rows to the geocode CSV."""
    output_csv = Path(output_csv)
    cache_path = Path(cache_path)

    if targets is None:
        targets = missing_geocode_targets()

    if skip_existing:
        have = _existing_geocoded_keys()
        targets = [target for target in targets if target.affiliation_key not in have]

    if not targets:
        return pd.DataFrame()

    api_key = load_google_maps_api_key()
    google_cache = _load_google_cache(cache_path)
    api_calls: list[int] = []
    rows: list[dict[str, Any]] = []

    for target in targets:
        anchor = resolve_country_anchor_fallback(target.organisation, target.country)
        if anchor is not None:
            city, lat, lon, query_label = anchor
            rows.append(
                {
                    "affiliation_key": target.affiliation_key,
                    "organisation": target.organisation,
                    "country": target.country,
                    "affiliation": target.affiliation,
                    "query_used": query_label,
                    "latitude": lat,
                    "longitude": lon,
                    "formatted_address": f"{city}, {target.country}",
                    "status": "FALLBACK",
                }
            )
            continue

        hit = google_geocode_affiliation(
            target.affiliation,
            api_key=api_key,
            google_cache=google_cache,
            pause_seconds=pause_seconds,
            api_calls=api_calls,
        )
        if hit is None:
            rows.append(
                {
                    "affiliation_key": target.affiliation_key,
                    "organisation": target.organisation,
                    "country": target.country,
                    "affiliation": target.affiliation,
                    "query_used": target.affiliation,
                    "latitude": "",
                    "longitude": "",
                    "formatted_address": "",
                    "status": "ZERO_RESULTS",
                }
            )
            continue

        rows.append(
            {
                "affiliation_key": target.affiliation_key,
                "organisation": target.organisation,
                "country": target.country,
                "affiliation": target.affiliation,
                "query_used": hit.get("query_used") or hit.get("query") or target.affiliation,
                "latitude": hit.get("latitude"),
                "longitude": hit.get("longitude"),
                "formatted_address": hit.get("formatted_address") or "",
                "status": "OK",
            }
        )

    result = pd.DataFrame(rows)
    if dry_run:
        return result

    _save_google_cache(cache_path, google_cache)

    if output_csv.exists():
        existing = pd.read_csv(output_csv, encoding="utf-8", encoding_errors="replace")
        if "affiliation_key" not in existing.columns:
            existing["affiliation_key"] = ""
        combined = pd.concat([existing, result], ignore_index=True)
        if "affiliation_key" in combined.columns:
            combined["_key"] = combined["affiliation_key"].astype(str).str.strip()
            combined["_has_key"] = combined["_key"].ne("")
            combined = combined.sort_values(["_has_key", "_key"], ascending=[True, True])
            combined = combined.drop_duplicates(
                subset=["_key"],
                keep="last",
            ).drop(columns=["_key", "_has_key"], errors="ignore")
        combined.to_csv(output_csv, index=False)
    else:
        result.to_csv(output_csv, index=False)

    meta = {
        "targets": len(targets),
        "api_calls": len(api_calls),
        "ok": int((result["status"] == "OK").sum()) if not result.empty else 0,
        "failed": int((result["status"] != "OK").sum()) if not result.empty else 0,
        "cache_path": str(cache_path),
        "output_csv": str(output_csv),
    }
    meta_path = output_csv.with_suffix(".refresh.json")
    meta_path.write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")

    return result
