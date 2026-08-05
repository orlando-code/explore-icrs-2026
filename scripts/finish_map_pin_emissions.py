#!/usr/bin/env python3
"""Query emissions.dev only for routes needed by on-map affiliation pins."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from rich.console import Console

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.delegates import (
    DEFAULT_DELEGATE_PDF_PATH,
    combined_attendee_talks,
    load_delegates,
)
from src.geocode import canonical_affiliation_key
from src.travel_emissions import (
    DEFAULT_EMISSIONS_SITE_PATH,
    DEFAULT_OUTPUT_PATH,
    DEFAULT_TRAVEL_CACHE_PATH,
    NZ_CAR_PASSENGERS_CENTRAL,
    api_query_count,
    attach_route_emissions,
    estimate_unique_routes,
    export_emissions_site_data,
    load_api_key,
    load_attendee_legs,
    load_geocoded_talks,
    load_site_locations,
    summarize_travel_emissions,
)

console = Console()

ALL_DELEGATES_OUTPUT_PATH = Path("outputs/travel_emissions_all_delegates_summary.json")
ALL_DELEGATES_DETAILS_PATH = Path("outputs/travel_emissions_all_delegates_by_attendee.csv")
SPEAKER_DETAILS_PATH = Path("outputs/travel_emissions_by_attendee.csv")
SPEAKER_SUMMARY_PATH = DEFAULT_OUTPUT_PATH


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--keys-path", type=Path, default=Path("keys.yaml"))
    parser.add_argument(
        "--api-key-name",
        default="third-emissions-dev",
        help="YAML key name for emissions.dev (default: third-emissions-dev).",
    )
    parser.add_argument("--travel-cache", type=Path, default=DEFAULT_TRAVEL_CACHE_PATH)
    parser.add_argument("--site-output", type=Path, default=DEFAULT_EMISSIONS_SITE_PATH)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show route counts without calling the API.",
    )
    parser.add_argument(
        "--smoke-test",
        action="store_true",
        help="Query one uncached route only.",
    )
    return parser.parse_args()


def _site_pin_keys(locations_path: Path = Path("js/locations.js")) -> set[str]:
    keys: set[str] = set()
    for location in load_site_locations(locations_path):
        affiliation = str(location.get("affiliation") or "").strip()
        if not affiliation:
            continue
        keys.add(canonical_affiliation_key(affiliation).casefold())
    return keys


def _filter_legs_to_site_pins(legs, site_keys: set[str]):
    import pandas as pd

    from src.travel_emissions import _clean_affiliation_value

    def _on_site_pin(value) -> bool:
        if value is None or (isinstance(value, float) and pd.isna(value)) or pd.isna(value):
            return False
        return canonical_affiliation_key(_clean_affiliation_value(value)).casefold() in site_keys

    mask = legs["affiliation"].map(_on_site_pin)
    return legs.loc[mask].copy()


def _estimate_rows(legs) -> list[TravelEstimate]:
    records: list[TravelEstimate] = []
    for _, row in legs.iterrows():
        records.append(
            TravelEstimate(
                presenter=str(row["presenter"]),
                affiliation=str(row["affiliation"]),
                transport_mode=str(row["transport_mode"]),
                origin_country=str(row["origin_country"]),
                origin_location=str(row["origin_location"]),
                geocode_level=row.get("geocode_level"),
                co2e_kg=float(row["co2e_kg"]),
                co2e_low_kg=float(row["co2e_low_kg"]),
                co2e_high_kg=float(row["co2e_high_kg"]),
                distance_km=None
                if row.get("distance_km") is None or str(row.get("distance_km")) == "nan"
                else float(row["distance_km"]),
                passengers=NZ_CAR_PASSENGERS_CENTRAL
                if row["transport_mode"] == "car"
                else 1,
                return_trip=True,
                query_used=row.get("query_used") or {},
            )
        )
    return records


def _upsert_estimates(existing, new, site_keys: set[str]):
    import pandas as pd

    if existing.empty:
        return new.copy()

    existing = existing.copy()
    new_keys = {
        (
            str(row["presenter"]),
            canonical_affiliation_key(str(row["affiliation"])).casefold(),
        )
        for _, row in new.iterrows()
    }
    keep_mask = ~existing.apply(
        lambda row: (
            canonical_affiliation_key(str(row["affiliation"] or "")).casefold() in site_keys
            and (
                str(row["presenter"]),
                canonical_affiliation_key(str(row["affiliation"] or "")).casefold(),
            ) in new_keys
        ),
        axis=1,
    )
    return pd.concat([existing.loc[keep_mask], new], ignore_index=True)


def _load_csv(path: Path):
    import pandas as pd

    if not path.exists():
        return pd.DataFrame()
    return pd.read_csv(path)


def _save_outputs(estimates, summary, summary_path: Path, details_path: Path) -> None:
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    details_path.parent.mkdir(parents=True, exist_ok=True)
    with summary_path.open("w", encoding="utf-8") as handle:
        json.dump(summary, handle, indent=2)
    estimates.to_csv(details_path, index=False)


def main() -> None:
    args = parse_args()
    site_keys = _site_pin_keys()
    console.print(f"[bold]Map pin affiliations:[/] {len(site_keys):,}")

    delegates = load_delegates() if DEFAULT_DELEGATE_PDF_PATH.exists() else None
    delegate_meta = {}
    if delegates is not None:
        non_speakers = delegates.loc[~delegates["is_speaker"]]
        delegate_meta = {
            "delegate_list_count": int(len(delegates)),
            "speaker_count": int(delegates["is_speaker"].sum()),
            "non_speaker_count": int(len(non_speakers)),
            "source_pdf": str(DEFAULT_DELEGATE_PDF_PATH),
        }

    speaker_talks = load_geocoded_talks()
    all_talks = (
        combined_attendee_talks(
            speaker_talks,
            include_non_speakers=True,
            delegates=delegates,
            show_progress=True,
        )
        if delegates is not None
        else speaker_talks
    )

    all_legs, all_missing = load_attendee_legs(all_talks, show_progress=True)
    pin_legs = _filter_legs_to_site_pins(all_legs, site_keys)
    console.print(
        f"[bold]Attendees on map pins:[/] {len(pin_legs):,} legs · "
        f"{pin_legs['affiliation'].nunique():,} affiliations"
    )

    valid_routes = pin_legs.drop_duplicates(
        subset=["origin_country", "origin_location", "transport_mode"]
    )
    valid_routes = valid_routes[
        valid_routes["origin_country"].astype(str).str.fullmatch(r"[A-Z]{2}", na=False)
    ]
    console.print(f"[bold]Unique routes for map pins:[/] {len(valid_routes):,}")

    if args.dry_run:
        from src.travel_emissions import _cache_key, _central_params_for_route

        cache = json.loads(args.travel_cache.read_text(encoding="utf-8"))
        uncached = 0
        for row in valid_routes.itertuples(index=False):
            params = _central_params_for_route(
                str(row.origin_country),
                str(row.origin_location),
                str(row.transport_mode),
            )
            if _cache_key(params) not in cache:
                uncached += 1
        console.print(f"[yellow]Uncached routes (would query):[/] {uncached:,}")
        return

    api_key = load_api_key(args.keys_path, key_name=args.api_key_name)
    route_limit = 1 if args.smoke_test else None

    routes = estimate_unique_routes(
        pin_legs,
        api_key=api_key,
        travel_cache_path=args.travel_cache,
        show_progress=True,
        limit=route_limit,
    )
    pin_estimates = attach_route_emissions(pin_legs, routes).dropna(subset=["co2e_kg"])
    console.print(
        f"[green]Estimated map-pin attendees:[/] {len(pin_estimates):,} · "
        f"API queries this run: {api_query_count():,}"
    )

    if args.smoke_test:
        console.print("[green]Smoke test passed.[/] Re-run without --smoke-test.")
        return

    pin_estimates_df = pin_estimates.copy()
    pin_estimates_df["passengers"] = pin_estimates_df["transport_mode"].map(
        lambda mode: NZ_CAR_PASSENGERS_CENTRAL if mode == "car" else 1
    )
    pin_estimates_df["return_trip"] = True
    pin_estimates_df["query_used"] = ""
    export_cols = [
        "presenter",
        "affiliation",
        "transport_mode",
        "origin_country",
        "origin_location",
        "geocode_level",
        "co2e_kg",
        "co2e_low_kg",
        "co2e_high_kg",
        "distance_km",
        "passengers",
        "return_trip",
        "query_used",
    ]
    pin_estimates_df = pin_estimates_df[export_cols]

    delegate_estimates = _upsert_estimates(
        _load_csv(ALL_DELEGATES_DETAILS_PATH),
        pin_estimates_df,
        site_keys,
    )
    delegate_summary = summarize_travel_emissions(
        delegate_estimates,
        missing_count=len(all_missing),
        total_presenters=all_talks["presenter"].nunique(),
        unique_routes=len(routes),
        api_queries=api_query_count(),
        attendee_label="delegates",
        exclusion_note=(
            "Delegates without geocoded affiliations are excluded. "
            f"The published list has {delegate_meta.get('delegate_list_count', 0):,} names; "
            f"{delegate_meta.get('non_speaker_count', 0):,} are not programme speakers."
        ),
    )
    _save_outputs(
        delegate_estimates,
        delegate_summary,
        ALL_DELEGATES_OUTPUT_PATH,
        ALL_DELEGATES_DETAILS_PATH,
    )

    speaker_presenters = set(speaker_talks["presenter"].astype(str))
    speaker_pin_estimates = pin_estimates_df[
        pin_estimates_df["presenter"].astype(str).isin(speaker_presenters)
    ].copy()
    speaker_estimates = _upsert_estimates(
        _load_csv(SPEAKER_DETAILS_PATH),
        speaker_pin_estimates,
        site_keys,
    )
    speaker_legs, speaker_missing = load_attendee_legs(speaker_talks, show_progress=False)
    speaker_summary = summarize_travel_emissions(
        speaker_estimates,
        missing_count=len(speaker_missing),
        total_presenters=speaker_talks["presenter"].nunique(),
        unique_routes=len(routes),
        api_queries=api_query_count(),
    )
    _save_outputs(
        speaker_estimates,
        speaker_summary,
        SPEAKER_SUMMARY_PATH,
        SPEAKER_DETAILS_PATH,
    )

    locations = load_site_locations("js/locations.js")
    export_emissions_site_data(
        speaker_estimates,
        speaker_summary,
        locations,
        legs=speaker_legs,
        all_delegates=(delegate_estimates, delegate_summary, all_legs),
        delegate_meta=delegate_meta,
        save_path=args.site_output,
        show_progress=True,
    )
    console.print(f"[green]Saved site export to[/] {args.site_output}")


if __name__ == "__main__":
    main()
