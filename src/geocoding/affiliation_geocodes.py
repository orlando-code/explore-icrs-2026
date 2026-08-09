"""Load OK rows from data/affiliation_geocodes.csv and attach to talks/delegates."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd

from src.geocoding.capital_coords import (
    coords_plausible_for_country,
    organisation_country_mismatch,
    resolve_capital_fallback,
    resolve_country_anchor_fallback,
)
from src.sources.delegates import normalize_person_name, country_to_iso2
from src.registry.affiliation_registry import parse_affiliation_parts
from src.geocoding.geocode import (
    DEFAULT_OVERRIDES_PATH,
    _load_json,
    _lookup_override,
    canonical_affiliation_key,
)
from src.data_paths import (
    AFFILIATION_GEOCODES_CSV,
    AFFILIATION_GEOCODES_MANUAL_CSV,
    GEOCODE_OVERRIDES_JSON,
)

DEFAULT_GEOCODES_CSV = AFFILIATION_GEOCODES_CSV
DEFAULT_MANUAL_GEOCODES_CSV = AFFILIATION_GEOCODES_MANUAL_CSV
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


def load_geocode_source_frames(
  path: Path | str = DEFAULT_GEOCODES_CSV,
  *,
  manual_path: Path | str = DEFAULT_MANUAL_GEOCODES_CSV,
) -> pd.DataFrame:
    """Load main and manual geocode CSVs, deduped by org+country (best status wins)."""
    frames: list[pd.DataFrame] = []
    for candidate in (Path(path), Path(manual_path)):
        if candidate.exists():
            frames.append(pd.read_csv(candidate, encoding="utf-8", encoding_errors="replace"))
    if not frames:
        return pd.DataFrame()
    combined = pd.concat(frames, ignore_index=True)
    combined["_priority"] = combined["status"].map(
        lambda value: {"OK": 3, "FALLBACK": 2, "IMPRECISE": 1}.get(str(value).strip(), 0)
    )
    combined["_org"] = combined["organisation"].astype(str).str.strip().str.casefold()
    combined["_country"] = combined["country"].astype(str).str.strip().str.casefold()
    combined = combined.sort_values(["_org", "_country", "_priority"], ascending=[True, True, False])
    return combined.drop_duplicates(subset=["_org", "_country"], keep="first")


def load_ok_geocodes(
    path: Path | str = DEFAULT_GEOCODES_CSV,
    *,
    manual_path: Path | str = DEFAULT_MANUAL_GEOCODES_CSV,
    include_fallback: bool = False,
) -> pd.DataFrame:
    """Return geocode rows with OK coordinates (optionally include FALLBACK rows)."""
    df = load_geocode_source_frames(path, manual_path=manual_path)
    if df.empty:
        return df
    allowed = {"OK"} if not include_fallback else {"OK", "FALLBACK"}
    ok = df.loc[df["status"].isin(allowed)].copy()
    ok["latitude"] = pd.to_numeric(ok["latitude"], errors="coerce")
    ok["longitude"] = pd.to_numeric(ok["longitude"], errors="coerce")
    return ok.dropna(subset=["latitude", "longitude"]).reset_index(drop=True)


def _delegate_org_country_lookup() -> dict[str, tuple[str, str]]:
    """Presenter name → (organisation, country) from attended people in person_registry."""
    from src.registry.person_registry import DEFAULT_REGISTRY_PATH, load_person_registry

    lookup: dict[str, tuple[str, str]] = {}
    if not DEFAULT_REGISTRY_PATH.exists():
        return lookup
    for _, row in load_person_registry().iterrows():
        if str(row.get("attended") or "").strip().lower() not in {"true", "1", "yes"}:
            continue
        organisation = str(row.get("organisation") or "").strip()
        country = str(row.get("country") or "").strip()
        if not organisation:
            continue
        for name in (
            str(row.get("canonical_name") or "").strip(),
            *str(row.get("name_variants") or "").split(";"),
        ):
            name = name.strip()
            if not name:
                continue
            for key in {normalize_person_name(name), name.casefold()}:
                if key:
                    lookup[key] = (organisation, country)
    return lookup


def build_geocode_lookup(geocodes: pd.DataFrame) -> dict[str, Any]:
    """Build lookup tables for resolving organisation/country to coordinates."""
    by_affiliation: dict[str, dict[str, Any]] = {}
    by_org_country: dict[tuple[str, str], dict[str, Any]] = {}
    by_org: dict[str, list[dict[str, Any]]] = {}

    org_country_counts = (
        geocodes.groupby("organisation")["country"].nunique().to_dict()
        if not geocodes.empty
        else {}
    )

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
            canonical = canonical_affiliation_key(affiliation).casefold()
            if canonical != affiliation.casefold() and org_country_counts.get(organisation, 1) <= 1:
                by_affiliation[canonical] = record
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
            hit = {
                "latitude": float(override["latitude"]),
                "longitude": float(override["longitude"]),
                "formatted_address": "",
                "query_used": str(override.get("query_used") or "override"),
                "geocode_level": str(override.get("geocode_level") or "institute"),
                "geocoded": True,
                "organisation": organisation or parse_affiliation_parts(affiliation)[0],
                "country": country or parse_affiliation_parts(affiliation)[1],
                "affiliation": affiliation,
            }
            return _accept_org_country_hit(
                hit,
                organisation=organisation or parse_affiliation_parts(affiliation)[0],
                country=country or parse_affiliation_parts(affiliation)[1],
                affiliation=affiliation,
            )
    return None


def _capital_fallback_record(
    organisation: str,
    country: str,
    affiliation: str,
) -> dict[str, Any] | None:
    require = bool(str(country or "").strip())
    anchor = resolve_country_anchor_fallback(organisation, country, require=require)
    if anchor is None:
        anchor = resolve_capital_fallback(organisation, country, require=require)
    if anchor is None:
        return None
    city, lat, lon, query_label = anchor
    return {
        "latitude": lat,
        "longitude": lon,
        "formatted_address": f"{city}, {country}",
        "query_used": query_label,
        "geocode_level": "country",
        "geocoded": True,
        "organisation": organisation,
        "country": country,
        "affiliation": affiliation,
    }


def _accept_org_country_hit(
    hit: dict[str, Any] | None,
    *,
    organisation: str,
    country: str,
    affiliation: str,
) -> dict[str, Any] | None:
    if hit is None:
        return None
    if not organisation_country_mismatch(organisation, country):
        return hit
    lat = hit.get("latitude")
    lon = hit.get("longitude")
    if lat is None or lon is None:
        return hit
    if coords_plausible_for_country(float(lat), float(lon), country):
        return hit
    return _capital_fallback_record(organisation, country, affiliation)


def _org_country_hit(
    organisation: str,
    country: str,
    *,
    affiliation: str,
    lookup: dict[str, Any],
) -> dict[str, Any] | None:
    anchor_hit = _capital_fallback_record(organisation, country, affiliation)
    if organisation_country_mismatch(organisation, country) and anchor_hit is not None:
        return anchor_hit

    composite = f"{organisation}, {country}"
    hit = lookup["by_affiliation"].get(composite.casefold())
    hit = _accept_org_country_hit(
        hit, organisation=organisation, country=country, affiliation=affiliation
    )
    if hit is not None:
        return hit

    hit = lookup["by_org_country"].get(
        (organisation.casefold(), country.casefold())
    )
    hit = _accept_org_country_hit(
        hit, organisation=organisation, country=country, affiliation=affiliation
    )
    if hit is not None:
        return hit

    return anchor_hit or _capital_fallback_record(organisation, country, affiliation)


def _geocode_lookup_candidates(
    affiliation: str,
    *,
    organisation: str = "",
    country: str = "",
) -> list[str]:
    from src.geocoding.geocode import affiliation_display_name, resolve_affiliation_alias

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

    organisation, country = parse_affiliation_parts(affiliation)
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
            parse_affiliation_parts(candidate)[0]
            for candidate in lookup_candidates
            if parse_affiliation_parts(candidate)[0]
        ),
        organisation,
    )

    if lookup_org and country:
        hit = _org_country_hit(
            lookup_org,
            country,
            affiliation=affiliation,
            lookup=lookup,
        )
        if hit is not None:
            return hit

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

    for candidate in lookup_candidates:
        hit = lookup["by_affiliation"].get(candidate.casefold())
        if hit is not None:
            if country and str(hit.get("country") or "").strip().casefold() != country.casefold():
                continue
            return hit
        if not country:
            hit = lookup["by_affiliation"].get(
                canonical_affiliation_key(candidate).casefold()
            )
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
        elif len(candidates) == 1 and not organisation_country_mismatch(
            lookup_org, country
        ):
            return candidates[0]

    return None


def attach_affiliation_geocodes(
    talks: pd.DataFrame,
    *,
    geocodes_path: Path | str = DEFAULT_GEOCODES_CSV,
    show_progress: bool = False,
) -> pd.DataFrame:
    """Attach latitude/longitude from affiliation_geocodes.csv (OK rows only)."""
    from src.registry.affiliation_lookup import AffiliationIndex, registry_geocode_hit
    from src.registry.affiliation_registry import parse_affiliation_parts
    from src.sources.delegates import resolve_compound_org_country
    from src.site.export_progress import iterrows_with_progress

    geocodes = load_ok_geocodes(geocodes_path)
    lookup = build_geocode_lookup(geocodes)
    delegate_lookup = _delegate_org_country_lookup()
    affiliation_index = AffiliationIndex.load()

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
        affiliation_text = str(affiliation).strip()
        organisation, country = parse_affiliation_parts(affiliation_text)
        organisation, country = resolve_compound_org_country(organisation, country)
        if organisation and country:
            affiliation_text = f"{organisation}, {country}"
        hit = resolve_geocode(
            affiliation_text,
            presenter=str(row.get("presenter") or ""),
            lookup=lookup,
            delegate_lookup=delegate_lookup,
        )
        if hit is None:
            hit = registry_geocode_hit(
                organisation or affiliation_text,
                country,
                index=affiliation_index,
            )
        if organisation and country:
            enriched.at[index, "affiliation"] = f"{organisation}, {country}"
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
    from src.geocoding.geocode import (
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
        "/** Generated from data/geocodes/geocode_overrides.json – do not edit by hand. */\n"
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
