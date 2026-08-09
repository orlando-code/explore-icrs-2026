"""Registry-based verification helpers for pipeline stages."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pandas as pd

from src.registry.affiliation_lookup import AffiliationIndex
from src.sources.delegates import load_delegates, normalize_person_name
from src.geocoding.capital_data import countries_missing_capital_data
from src.registry.person_registry import load_person_registry
from src.data_paths import PERSON_ALIASES_CSV, PERSON_REGISTRY_CSV


def _truthy_series(series: pd.Series) -> pd.Series:
    return series.astype(str).str.strip().str.lower().isin({"true", "1", "yes"})


def _geocoded(frame: pd.DataFrame) -> pd.Series:
    if frame.empty:
        return pd.Series(dtype=bool)
    status = frame.get("geocode_status", pd.Series(dtype=str)).astype(str).str.lower()
    return status.isin({"ok", "fallback"})


def parse_emissions_js(path: Path | str) -> dict[str, Any]:
    """Load EMISSIONS_DATA from js/emissions-data.js."""
    text = Path(path).read_text(encoding="utf-8")
    match = re.search(r"export const EMISSIONS_DATA = (\{.*\});\s*$", text, re.S)
    if not match:
        raise ValueError(f"Could not parse emissions export in {path}")
    return json.loads(match.group(1))


def _load_name_aliases_by_person() -> dict[str, set[str]]:
    path = PERSON_ALIASES_CSV
    if not path.exists():
        return {}
    aliases = pd.read_csv(path)
    by_person: dict[str, set[str]] = {}
    for _, row in aliases.iterrows():
        person_key = str(row.get("person_key") or "").strip()
        for column in ("name_variant", "normalized_name"):
            name = str(row.get(column) or "").strip()
            if person_key and name:
                by_person.setdefault(person_key, set()).add(normalize_person_name(name))
    return by_person


def _person_name_keys(person_key: str, canonical_name: str, alias_map: dict[str, set[str]]) -> set[str]:
    keys = {normalize_person_name(canonical_name)}
    keys.update(alias_map.get(person_key, set()))
    return {key for key in keys if key}


def _emissions_attendees_by_name(pool: dict[str, Any]) -> dict[str, dict[str, Any]]:
    by_name: dict[str, dict[str, Any]] = {}
    for attendee in pool.get("attendees", []):
        name = str(attendee.get("name") or "").strip()
        if not name:
            continue
        by_name[normalize_person_name(name)] = attendee
    return by_name


def _match_pool_row(
    name_keys: set[str], pool: dict[str, dict[str, Any]]
) -> dict[str, Any] | None:
    for key in name_keys:
        if key in pool:
            return pool[key]
    return None


def verify_registry_coverage() -> dict[str, Any]:
    """Summarise person and affiliation registry readiness for map/emissions."""
    people = load_person_registry(PERSON_REGISTRY_CSV)
    index = AffiliationIndex.load()
    affiliations = index.registry.reset_index(drop=True)

    attended = people.loc[_truthy_series(people["attended"])].copy()
    attended["_affiliation_key"] = attended.apply(
        lambda row: index.resolve_key(
            str(row.get("organisation") or ""),
            str(row.get("country") or ""),
        ),
        axis=1,
    )
    attended["_has_affiliation"] = attended["_affiliation_key"].astype(str).str.strip().ne("")
    attended["_geocoded"] = attended.apply(
        lambda row: index.is_geocoded(str(row.get("organisation") or ""), str(row.get("country") or "")),
        axis=1,
    )
    attended["_plot_on_map"] = attended.apply(
        lambda row: index.plot_on_map(str(row.get("organisation") or ""), str(row.get("country") or "")),
        axis=1,
    )

    plot_affiliations = affiliations.loc[_truthy_series(affiliations.get("plot_on_map", pd.Series(False)))]

    metrics: dict[str, Any] = {
        "people_total": len(people),
        "people_attended": len(attended),
        "affiliations_total": len(affiliations),
        "affiliations_plot_on_map": len(plot_affiliations),
        "affiliations_geocoded": int(_geocoded(affiliations).sum()),
        "affiliation_geocode_pct": round(
            100.0 * int(_geocoded(affiliations).sum()) / max(len(affiliations), 1),
            2,
        ),
        "attended_with_affiliation": int(attended["_has_affiliation"].sum()),
        "attended_geocoded": int(attended["_geocoded"].sum()),
        "attended_geocode_pct": round(
            100.0 * int(attended["_geocoded"].sum()) / max(len(attended), 1),
            2,
        ),
        "attended_plot_on_map": int(attended["_plot_on_map"].sum()),
        "affiliations_needs_review": int(
            _truthy_series(affiliations.get("needs_review", pd.Series(False))).sum()
        ),
        "compound_redirects": int(
            affiliations.get("redirect_to_affiliation_key", pd.Series(dtype=str))
            .astype(str)
            .str.strip()
            .ne("")
            .sum()
        ),
    }

    missing = attended.loc[
        ~attended["_geocoded"],
        ["canonical_name", "organisation", "country", "_affiliation_key"],
    ]
    metrics["attended_missing_geocode"] = len(missing)
    if not missing.empty:
        metrics["attended_missing_geocode_sample"] = missing.head(8).to_dict(orient="records")

    return metrics


def verify_capital_data_coverage() -> dict[str, Any]:
    """Ensure every delegate-list country has capital coordinates in geography data."""
    delegates = load_delegates()
    countries = sorted(
        {
            str(value).strip()
            for value in delegates["country"].astype(str)
            if str(value).strip()
        }
    )
    missing = countries_missing_capital_data(countries)
    return {
        "delegate_countries_total": len(countries),
        "delegate_countries_missing_capital_data": len(missing),
        "missing_capital_data": [
            {"country": country, "iso2": iso2} for country, iso2 in missing
        ],
    }


def build_attendee_artifact() -> pd.DataFrame:
    """One row per attended person with resolved affiliation geocode metadata."""
    people = load_person_registry(PERSON_REGISTRY_CSV)
    index = AffiliationIndex.load()

    attended = people.loc[_truthy_series(people["attended"])].copy()
    attended["affiliation_key"] = attended.apply(
        lambda row: index.resolve_key(
            str(row.get("organisation") or ""),
            str(row.get("country") or ""),
        ),
        axis=1,
    )
    affiliation_cols = [
        "affiliation_key",
        "canonical_affiliation",
        "organisation",
        "country",
        "geocode_status",
        "latitude",
        "longitude",
        "plot_on_map",
        "redirect_to_affiliation_key",
    ]
    aff = index.registry.reset_index(drop=True).reindex(columns=affiliation_cols, fill_value="")
    aff = aff.add_suffix("_affiliation")
    merged = attended.merge(
        aff,
        left_on="affiliation_key",
        right_on="affiliation_key_affiliation",
        how="left",
    )
    return merged.sort_values(["canonical_name", "organisation"]).reset_index(drop=True)


def build_emissions_coverage_artifact(
    *,
    emissions_js: Path | str,
    legs_path: Path | str | None = None,
    estimates_path: Path | str | None = None,
) -> pd.DataFrame:
    """One row per attended person with geocode / travel-leg / emissions status."""
    emissions_js = Path(emissions_js)
    payload = parse_emissions_js(emissions_js)

    people = load_person_registry(PERSON_REGISTRY_CSV)
    attended = people.loc[_truthy_series(people["attended"])].copy()
    index = AffiliationIndex.load()

    speakers = _emissions_attendees_by_name(payload.get("speakers", {}))
    delegates_pool = _emissions_attendees_by_name(
        payload.get("all_delegates", payload.get("speakers", {}))
    )
    alias_map = _load_name_aliases_by_person()

    leg_names: set[str] = set()
    if legs_path and Path(legs_path).exists():
        legs = pd.read_csv(legs_path)
        leg_names = {
            normalize_person_name(name)
            for name in legs.get("presenter", pd.Series(dtype=str)).astype(str)
            if str(name).strip()
        }

    estimate_names: set[str] = set()
    if estimates_path and Path(estimates_path).exists():
        estimates = pd.read_csv(estimates_path)
        estimate_names = {
            normalize_person_name(name)
            for name in estimates.get("presenter", pd.Series(dtype=str)).astype(str)
            if str(name).strip()
        }

    rows: list[dict[str, Any]] = []
    for _, person in attended.iterrows():
        organisation = str(person.get("organisation") or "").strip()
        country = str(person.get("country") or "").strip()
        person_key = str(person.get("person_key") or "").strip()
        name_keys = _person_name_keys(
            person_key, str(person.get("canonical_name") or ""), alias_map
        )
        registry_geocoded = index.is_geocoded(organisation, country)
        speaker_row = _match_pool_row(name_keys, speakers)
        delegate_row = _match_pool_row(name_keys, delegates_pool)
        co2e_kg = float(delegate_row.get("co2e_kg") or 0) if delegate_row else 0.0
        has_travel_leg = any(key in leg_names for key in name_keys)
        has_route_estimate = any(key in estimate_names for key in name_keys)

        if co2e_kg > 0:
            status = "ok"
        elif not registry_geocoded:
            status = "no_geocode"
        elif not has_travel_leg:
            status = "no_travel_leg"
        elif has_route_estimate and not delegate_row:
            status = "excluded"
        elif has_travel_leg and not has_route_estimate:
            status = "no_route_cache"
        else:
            status = "no_emissions"

        rows.append(
            {
                "person_key": person.get("person_key"),
                "canonical_name": person.get("canonical_name"),
                "is_speaker": person.get("is_speaker"),
                "organisation": organisation,
                "country": country,
                "affiliation_key": index.resolve_key(organisation, country),
                "registry_geocoded": registry_geocoded,
                "has_travel_leg": has_travel_leg,
                "has_route_estimate": has_route_estimate,
                "in_speakers_emissions": speaker_row is not None,
                "in_all_delegates_emissions": delegate_row is not None,
                "co2e_kg": co2e_kg,
                "emissions_status": status,
            }
        )

    return pd.DataFrame(rows).sort_values(
        ["emissions_status", "canonical_name"]
    ).reset_index(drop=True)


def verify_emissions_coverage(
    *,
    emissions_js: Path | str,
    legs_path: Path | str | None = None,
    estimates_path: Path | str | None = None,
) -> dict[str, Any]:
    """Summarise how many attended people have travel emissions in the export."""
    frame = build_emissions_coverage_artifact(
        emissions_js=emissions_js,
        legs_path=legs_path,
        estimates_path=estimates_path,
    )
    attended = len(frame)
    speakers = int(_truthy_series(frame["is_speaker"]).sum()) if not frame.empty else 0

    status_counts = (
        frame["emissions_status"].value_counts().to_dict() if not frame.empty else {}
    )
    with_co2e = int((frame["co2e_kg"].fillna(0) > 0).sum()) if not frame.empty else 0
    registry_geocoded = int(frame["registry_geocoded"].sum()) if not frame.empty else 0
    with_legs = int(frame["has_travel_leg"].sum()) if not frame.empty else 0

    metrics: dict[str, Any] = {
        "people_attended": attended,
        "people_speakers": speakers,
        "registry_geocoded": registry_geocoded,
        "registry_geocode_pct": round(100.0 * registry_geocoded / max(attended, 1), 2),
        "with_travel_leg": with_legs,
        "with_travel_leg_pct": round(100.0 * with_legs / max(attended, 1), 2),
        "with_co2e_kg": with_co2e,
        "with_co2e_pct": round(100.0 * with_co2e / max(attended, 1), 2),
        "emissions_status_counts": status_counts,
        "missing_co2e": attended - with_co2e,
    }

    missing = frame.loc[frame["emissions_status"] != "ok"] if not frame.empty else frame
    metrics["missing_co2e_count"] = len(missing)
    if not missing.empty:
        metrics["missing_co2e_sample"] = (
            missing.head(12)[
                ["canonical_name", "organisation", "emissions_status", "registry_geocoded"]
            ]
            .to_dict(orient="records")
        )

    emissions_payload = parse_emissions_js(emissions_js)
    for pool_name in ("speakers", "all_delegates"):
        pool = emissions_payload.get(pool_name, {})
        headline = pool.get("meta", {}).get("headline", {})
        metrics[f"{pool_name}_pool_count"] = len(pool.get("attendees", []))
        metrics[f"{pool_name}_missing_location"] = headline.get("attendees_missing_location")

    return metrics
