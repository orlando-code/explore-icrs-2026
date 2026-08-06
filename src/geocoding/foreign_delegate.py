"""Foreign-institute / delegate-country anchoring and standardisation report.

When an organisation's physical home (from its name or institution rules) differs from
the delegate's country, we keep the organisation label but anchor map pins and travel
routes to the delegate country's capital (same pattern as BIOS, TNC, Bangor→Maldives).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd

from src.data_paths import AFFILIATION_REGISTRY_CSV, REGISTRY
from src.geocoding.capital_coords import (
    _countries_implied_by_organisation,
    coords_plausible_for_country,
    organisation_country_mismatch,
    resolve_capital_fallback,
)
from src.geocoding.geocode import (
    affiliation_display_name,
    canonical_affiliation_key,
)
from src.registry.affiliation_registry import _read_csv


def institute_home_countries(organisation: str) -> list[str]:
    """Countries where the institute name or rules say it is physically based."""
    return _countries_implied_by_organisation(organisation)


def foreign_delegate_anchor_reason(organisation: str, country: str) -> str:
    """Why this org+delegate-country pair uses a capital anchor, or empty if local."""
    organisation = str(organisation or "").strip()
    country = str(country or "").strip()
    if not organisation or not country:
        return ""
    if organisation_country_mismatch(organisation, country):
        return "institute_home_country_differs"
    return ""


def standardised_affiliation_label(organisation: str, country: str) -> str:
    """Display label: organisation name + delegate country (never renamed to capital)."""
    organisation = str(organisation or "").strip()
    country = str(country or "").strip()
    if organisation and country:
        return affiliation_display_name(f"{organisation}, {country}") or f"{organisation}, {country}"
    return organisation or country


def build_foreign_delegate_standardisation(
    registry_path: Path | str = AFFILIATION_REGISTRY_CSV,
    *,
    attended_only: bool = True,
) -> pd.DataFrame:
    """Report org+country rows where the institute home differs from delegate country."""
    registry = _read_csv(registry_path)
    if registry.empty:
        return pd.DataFrame()

    if attended_only and "attendee_count" in registry.columns:
        registry = registry.loc[pd.to_numeric(registry["attendee_count"], errors="coerce").fillna(0) > 0]

    rows: list[dict[str, Any]] = []
    for _, record in registry.iterrows():
        organisation = str(record.get("organisation") or "").strip()
        country = str(record.get("country") or "").strip()
        if not organisation or not country:
            continue

        reason = foreign_delegate_anchor_reason(organisation, country)
        lat = record.get("latitude")
        lon = record.get("longitude")
        try:
            lat_f = float(lat) if str(lat or "").strip() else None
            lon_f = float(lon) if str(lon or "").strip() else None
        except (TypeError, ValueError):
            lat_f, lon_f = None, None

        if not reason and lat_f is not None and lon_f is not None:
            homes = institute_home_countries(organisation)
            if not homes and not coords_plausible_for_country(lat_f, lon_f, country):
                reason = "geocode_coords_outside_delegate_country"

        if not reason:
            continue

        homes = institute_home_countries(organisation)
        fallback = resolve_capital_fallback(organisation, country)
        anchor_city = fallback[0] if fallback else ""
        std_label = standardised_affiliation_label(organisation, country)

        rows.append(
            {
                "affiliation_key": record.get("affiliation_key"),
                "organisation": organisation,
                "delegate_country": country,
                "institute_home_countries": "; ".join(homes) if homes else "",
                "standardised_affiliation": std_label,
                "canonical_affiliation_key": canonical_affiliation_key(std_label),
                "geocode_status": record.get("geocode_status"),
                "geocode_source": record.get("geocode_source"),
                "anchor_city": anchor_city,
                "latitude": lat_f,
                "longitude": lon_f,
                "attendee_count": record.get("attendee_count"),
                "anchor_reason": reason,
            }
        )

    if not rows:
        return pd.DataFrame()

    frame = pd.DataFrame(rows)
    return frame.sort_values(
        ["attendee_count", "organisation", "delegate_country"],
        ascending=[False, True, True],
    ).reset_index(drop=True)


def export_foreign_delegate_standardisation(
    output_path: Path | str | None = None,
    *,
    attended_only: bool = True,
) -> Path:
    """Write foreign-delegate standardisation CSV under pipeline/artifacts/."""
    from src.data_paths import PROJECT_ROOT

    output_path = Path(
        output_path or PROJECT_ROOT / "pipeline" / "artifacts" / "foreign_delegate_anchors.csv"
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    build_foreign_delegate_standardisation(attended_only=attended_only).to_csv(
        output_path, index=False
    )
    return output_path
