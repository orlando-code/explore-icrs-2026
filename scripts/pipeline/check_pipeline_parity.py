#!/usr/bin/env python3
"""Run pipeline verification and print parity summary for sign-off."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from pipeline.config import PipelineConfig
from pipeline.verify import build_emissions_coverage_artifact, verify_emissions_coverage, verify_registry_coverage


def _parse_locations_stats(path: Path) -> dict:
    text = path.read_text(encoding="utf-8")
    match = re.search(r'"stats"\s*:\s*(\{[^}]+\})', text)
    if not match:
        return {}
    return json.loads(match.group(1))


def main() -> int:
    config = PipelineConfig()
    print("=== Registry coverage ===")
    registry = verify_registry_coverage()
    for key in (
        "people_attended",
        "attended_geocoded",
        "attended_geocode_pct",
        "affiliations_needs_review",
    ):
        print(f"  {key}: {registry.get(key)}")

    emissions_js = config.emissions_js
    legs = config.artifact("emissions_travel_legs.csv")
    estimates = config.artifact("emissions_delegate_estimates.csv")
    print("\n=== Emissions coverage ===")
    if emissions_js.exists():
        metrics = verify_emissions_coverage(
            emissions_js=emissions_js,
            legs_path=legs if legs.exists() else None,
            estimates_path=estimates if estimates.exists() else None,
        )
        for key in (
            "with_co2e_kg",
            "with_co2e_pct",
            "missing_co2e_count",
            "emissions_status_counts",
        ):
            print(f"  {key}: {metrics.get(key)}")
    else:
        print("  emissions-data.js missing — run: python scripts/pipeline/build_pipeline.py emissions")

    locations_js = config.locations_js
    print("\n=== Map export ===")
    if locations_js.exists():
        stats = _parse_locations_stats(locations_js)
        for key in ("location_count", "speaker_count", "connection_count"):
            if key in stats:
                print(f"  {key}: {stats[key]}")
        print(f"  file_bytes: {locations_js.stat().st_size:,}")
    else:
        print("  locations.js missing — run: python scripts/pipeline/build_pipeline.py export-site")

    if emissions_js.exists():
        coverage = build_emissions_coverage_artifact(
            emissions_js=emissions_js,
            legs_path=legs if legs.exists() else None,
            estimates_path=estimates if estimates.exists() else None,
        )
        not_ok = coverage.loc[coverage["emissions_status"] != "ok"]
        if not not_ok.empty:
            print("\n=== Remaining emissions gaps (first 15) ===")
            for _, row in not_ok.head(15).iterrows():
                print(
                    f"  {row['canonical_name']}: {row['emissions_status']} "
                    f"({row['organisation']}, {row['country']})"
                )

    ok = (
        registry.get("attended_geocode_pct", 0) >= 99
        and (not emissions_js.exists() or metrics.get("with_co2e_pct", 0) >= 95)
    )
    print(f"\n{'READY' if ok else 'REVIEW'} for parity sign-off")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
