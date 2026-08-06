"""Load OK rows from data/affiliation_geocodes.csv and attach to talks/delegates."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd

from src.capital_coords import resolve_capital_fallback
from src.delegates import load_delegates, normalize_person_name, country_to_iso2
from src.geocode import (
    DEFAULT_OVERRIDES_PATH,
    _load_json,
    _lookup_override,
    canonical_affiliation_key,
)

DEFAULT_GEOCODES_CSV = Path("data/affiliation_geocodes.csv")
_GEOCODE_OVERRIDES_CACHE: dict[str, dict] | None = None


def load_geocode_overrides(
    path: Path | str = DEFAULT_OVERRIDES_PATH,
) -> dict[str, dict]:
    """Load geocode overrides used as the highest-priority coordinate source."""
    global _GEOCODE_OVERRIDES_CACHE
    if _GEOCODE_OVERRIDES_CACHE is None:
        payload = _load_json(Path(path))
        _GEOCODE_OVERRIDES_CACHE = payload if isinstance(payload, dict) else {}
    return _GEOCODE_OVERRIDES_CACHE


def load_ok_geocodes(
    path: Path | str = DEFAULT_GEOCODES_CSV,
) -> pd.DataFrame:
    """Return geocode rows with status OK and finite coordinates."""
    df = pd.read_csv(path, encoding="utf-8", encoding_errors="replace")
    ok = df.loc[df["status"].eq("OK")].copy()
    ok["latitude"] = pd.to_numeric(ok["latitude"], errors="coerce")
    ok["longitude"] = pd.to_numeric(ok["longitude"], errors="coerce")
    return ok.dropna(subset=["latitude", "longitude"]).reset_index(drop=True)


def _parse_affiliation_parts(affiliation: str) -> tuple[str, str]:
    parts = [part.strip() for part in str(affiliation).split(",") if part.strip()]
    if not parts:
        return "", ""
    if len(parts) == 1:
        return parts[0], ""
    return parts[0], ", ".join(parts[1:])


def _delegate_org_country_lookup() -> dict[str, tuple[str, str]]:
    lookup: dict[str, tuple[str, str]] = {}
    for _, row in load_delegates(refresh=False).iterrows():
        organisation = str(row.get("organisation") or "").strip()
        country = str(row.get("country") or "").strip()
        if not organisation:
            continue
        for key in {
            normalize_person_name(str(row.get("full_name") or "")),
            str(row.get("full_name") or "").strip().casefold(),
        }:
            if key:
                lookup[key] = (organisation, country)
    return lookup


def build_geocode_lookup(geocodes: pd.DataFrame) -> dict[str, Any]:
    """Build lookup tables for resolving organisation/country to coordinates."""
    by_affiliation: dict[str, dict[str, Any]] = {}
    by_org_country: dict[tuple[str, str], dict[str, Any]] = {}
    by_org: dict[str, list[dict[str, Any]]] = {}

    for row in geocodes.to_dict(orient="records"):
        organisation = str(row.get("organisation") or "").strip()
        country = str(row.get("country") or "").strip()
        affiliation = str(row.get("affiliation") or "").strip()
        record = {
            "latitude": float(row["latitude"]),
            "longitude": float(row["longitude"]),
            "formatted_address": str(row.get("formatted_address") or ""),
            "query_used": str(row.get("query_used") or ""),
            "geocode_level": "institute",
            "geocoded": True,
            "organisation": organisation,
            "country": country,
            "affiliation": affiliation,
        }
        if affiliation:
            by_affiliation[affiliation.casefold()] = record
            by_affiliation[canonical_affiliation_key(affiliation).casefold()] = record
        key = (organisation.casefold(), country.casefold())
        by_org_country[key] = record
        by_org.setdefault(organisation.casefold(), []).append(record)

    return {
        "by_affiliation": by_affiliation,
        "by_org_country": by_org_country,
        "by_org": by_org,
    }


def _override_hit(
    affiliation: str,
    override_lookup: dict[str, dict],
    *,
    organisation: str = "",
    country: str = "",
) -> dict[str, Any] | None:
    candidates = [affiliation]
    if organisation and country:
        candidates.append(f"{organisation}, {country}")
    for candidate in candidates:
        override = _lookup_override(candidate, override_lookup)
        if (
            override is not None
            and override.get("latitude") is not None
            and override.get("longitude") is not None
        ):
            return {
                "latitude": float(override["latitude"]),
                "longitude": float(override["longitude"]),
                "formatted_address": "",
                "query_used": str(override.get("query_used") or "override"),
                "geocode_level": str(override.get("geocode_level") or "institute"),
                "geocoded": True,
                "organisation": organisation or _parse_affiliation_parts(affiliation)[0],
                "country": country or _parse_affiliation_parts(affiliation)[1],
                "affiliation": affiliation,
            }
    return None


def _org_country_hit(
    organisation: str,
    country: str,
    *,
    affiliation: str,
    lookup: dict[str, Any],
) -> dict[str, Any] | None:
    composite = f"{organisation}, {country}"
    for key in (composite.casefold(), canonical_affiliation_key(composite).casefold()):
        hit = lookup["by_affiliation"].get(key)
        if hit is not None:
            return hit

    hit = lookup["by_org_country"].get(
        (organisation.casefold(), country.casefold())
    )
    if hit is not None:
        return hit

    fallback = resolve_capital_fallback(organisation, country)
    if fallback is not None:
        _city, lat, lon, query_label = fallback
        return {
            "latitude": lat,
            "longitude": lon,
            "formatted_address": "",
            "query_used": query_label,
            "geocode_level": "country",
            "geocoded": True,
            "organisation": organisation,
            "country": country,
            "affiliation": affiliation,
        }
    return None


def _geocode_lookup_candidates(
    affiliation: str,
    *,
    organisation: str = "",
    country: str = "",
) -> list[str]:
    from src.geocode import affiliation_display_name, resolve_affiliation_alias

    candidates: list[str] = []
    for value in (
        affiliation,
        resolve_affiliation_alias(affiliation),
        affiliation_display_name(affiliation),
        organisation,
        resolve_affiliation_alias(organisation),
        affiliation_display_name(organisation),
        f"{organisation}, {country}" if organisation and country else "",
        f"{resolve_affiliation_alias(organisation)}, {country}"
        if organisation and country
        else "",
        f"{affiliation_display_name(organisation)}, {country}"
        if organisation and country
        else "",
    ):
        text = str(value or "").strip()
        if text and text not in candidates:
            candidates.append(text)
    return candidates


def resolve_geocode(
    affiliation: str,
    *,
    presenter: str = "",
    lookup: dict[str, Any] | None = None,
    delegate_lookup: dict[str, tuple[str, str]] | None = None,
    overrides: dict[str, dict] | None = None,
) -> dict[str, Any] | None:
    if lookup is None:
        lookup = build_geocode_lookup(load_ok_geocodes())

    affiliation = str(affiliation or "").strip()
    if not affiliation:
        return None

    organisation, country = _parse_affiliation_parts(affiliation)
    if not country and presenter:
        delegate = delegate_lookup or _delegate_org_country_lookup()
        match = delegate.get(normalize_person_name(presenter)) or delegate.get(
            presenter.strip().casefold()
        )
        if match:
            delegate_org, delegate_country = match
            organisation = organisation or delegate_org
            country = delegate_country

    lookup_candidates = _geocode_lookup_candidates(
        affiliation,
        organisation=organisation,
        country=country,
    )
    lookup_org = next(
        (
            _parse_affiliation_parts(candidate)[0]
            for candidate in lookup_candidates
            if _parse_affiliation_parts(candidate)[0]
        ),
        organisation,
    )

    override_lookup = overrides if overrides is not None else load_geocode_overrides()
    for candidate in lookup_candidates:
        override = _override_hit(
            candidate,
            override_lookup,
            organisation=lookup_org,
            country=country,
        )
        if override is not None:
            override["affiliation"] = affiliation
            return override

    if lookup_org and country:
        hit = _org_country_hit(
            lookup_org,
            country,
            affiliation=affiliation,
            lookup=lookup,
        )
        if hit is not None:
            return hit

    for candidate in lookup_candidates:
        hit = lookup["by_affiliation"].get(candidate.casefold())
        if hit is not None:
            return hit
        hit = lookup["by_affiliation"].get(canonical_affiliation_key(candidate).casefold())
        if hit is not None:
            return hit

    if lookup_org:
        candidates = lookup["by_org"].get(lookup_org.casefold(), [])
        if country:
            country_key = country.casefold()
            country_matches = [
                candidate
                for candidate in candidates
                if str(candidate.get("country") or "").casefold() == country_key
            ]
            if len(country_matches) == 1:
                return country_matches[0]
        elif len(candidates) == 1:
            return candidates[0]

    return None


def attach_affiliation_geocodes(
    talks: pd.DataFrame,
    *,
    geocodes_path: Path | str = DEFAULT_GEOCODES_CSV,
    show_progress: bool = False,
) -> pd.DataFrame:
    """Attach latitude/longitude from affiliation_geocodes.csv (OK rows only)."""
    from src.export_progress import iterrows_with_progress

    geocodes = load_ok_geocodes(geocodes_path)
    lookup = build_geocode_lookup(geocodes)
    delegate_lookup = _delegate_org_country_lookup()

    enriched = talks.copy()
    for column in (
        "latitude",
        "longitude",
        "geocoded",
        "geocode_level",
        "query_used",
        "formatted_address",
        "country_code",
    ):
        if column not in enriched.columns:
            enriched[column] = pd.NA

    for index, row in iterrows_with_progress(
        enriched,
        "Attaching affiliation geocodes to talks",
        show_progress=show_progress,
    ):
        affiliation = row.get("affiliation")
        if pd.isna(affiliation):
            continue
        hit = resolve_geocode(
            str(affiliation),
            presenter=str(row.get("presenter") or ""),
            lookup=lookup,
            delegate_lookup=delegate_lookup,
        )
        if hit is None:
            continue
        enriched.at[index, "latitude"] = hit["latitude"]
        enriched.at[index, "longitude"] = hit["longitude"]
        enriched.at[index, "geocoded"] = True
        enriched.at[index, "geocode_level"] = hit["geocode_level"]
        enriched.at[index, "query_used"] = hit["query_used"]
        enriched.at[index, "formatted_address"] = hit["formatted_address"]
        country = str(hit.get("country") or "").strip()
        if country:
            enriched.at[index, "country_code"] = country_to_iso2(country)

    return enriched


def export_geocode_overrides_js(
    save_path: str | Path = "js/geocode-overrides.js",
) -> Path:
    """Export data/geocode_overrides.json for runtime map pin correction."""
    from src.geocode import (
        affiliation_base_name,
        affiliation_display_name,
        load_affiliation_display_aliases,
    )

    overrides = load_geocode_overrides()
    entries: list[list[str | float]] = []
    seen: set[str] = set()

    def add(name: str, lat: float, lon: float) -> None:
        key = str(name or "").strip()
        if not key:
            return
        map_key = key.casefold()
        if map_key in seen:
            return
        seen.add(map_key)
        entries.append([key, lat, lon])

    for name, payload in sorted(overrides.items()):
        if payload.get("latitude") is None or payload.get("longitude") is None:
            continue
        add(name, float(payload["latitude"]), float(payload["longitude"]))

    aliases = load_affiliation_display_aliases()
    for source, target in aliases.items():
        for candidate in (
            target,
            affiliation_display_name(target),
            affiliation_base_name(target),
        ):
            override = overrides.get(candidate)
            if override is None or override.get("latitude") is None:
                continue
            add(
                source,
                float(override["latitude"]),
                float(override["longitude"]),
            )
            break

    entries.sort(key=lambda item: str(item[0]).casefold())
    output_path = Path(save_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    body = (
        "/** Generated from data/geocode_overrides.json – do not edit by hand. */\n"
        f"export const AFFILIATION_GEOCODE_OVERRIDE_ENTRIES = {json.dumps(entries, ensure_ascii=False, indent=2)};\n"
    )
    output_path.write_text(body, encoding="utf-8")
    return output_path


def geocode_affiliations_dataframe(
    affiliations: list[str] | pd.Series,
    *,
    geocodes_path: Path | str = DEFAULT_GEOCODES_CSV,
) -> pd.DataFrame:
    """Return one row per affiliation with coordinates when available."""
    geocodes = load_ok_geocodes(geocodes_path)
    lookup = build_geocode_lookup(geocodes)
    rows: list[dict[str, Any]] = []
    for affiliation in pd.Series(affiliations).dropna().astype(str).unique():
        affiliation = affiliation.strip()
        if not affiliation:
            continue
        hit = resolve_geocode(affiliation, lookup=lookup)
        rows.append(
            {
                "affiliation": affiliation,
                "latitude": hit["latitude"] if hit else pd.NA,
                "longitude": hit["longitude"] if hit else pd.NA,
                "geocoded": bool(hit),
                "geocode_level": hit.get("geocode_level") if hit else pd.NA,
                "query_used": hit.get("query_used") if hit else pd.NA,
                "formatted_address": hit.get("formatted_address") if hit else pd.NA,
            }
        )
    return pd.DataFrame(rows)
