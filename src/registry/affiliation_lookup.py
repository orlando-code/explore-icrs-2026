"""Resolve organisation+country to stable affiliation_key (icrs-a-*) rows."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

from src.registry.affiliation_registry import (
    DEFAULT_ALIASES_PATH,
    DEFAULT_REGISTRY_PATH,
    _make_affiliation,
    _read_csv,
    group_key,
    load_affiliation_registry,
)


def _geocoded_status(status: str) -> bool:
    return str(status or "").strip().lower() in {"ok", "fallback"}


@dataclass
class AffiliationIndex:
    """Fast lookup from org/country variants to affiliation registry rows."""

    registry: pd.DataFrame
    by_group_key: dict[str, str] = field(default_factory=dict)
    by_variant: dict[str, str] = field(default_factory=dict)
    redirects: dict[str, str] = field(default_factory=dict)

    @classmethod
    def load(cls, data_dir: Path | str | None = None) -> AffiliationIndex:
        registry = load_affiliation_registry(DEFAULT_REGISTRY_PATH)
        aliases = _read_csv(DEFAULT_ALIASES_PATH)
        return cls.from_frames(registry, aliases)

    @classmethod
    def from_frames(cls, registry: pd.DataFrame, aliases: pd.DataFrame) -> AffiliationIndex:
        by_group_key: dict[str, str] = {}
        by_variant: dict[str, str] = {}

        for _, row in registry.iterrows():
            key = str(row.get("affiliation_key") or "").strip()
            if not key:
                continue
            gkey = group_key(str(row.get("organisation") or ""), str(row.get("country") or ""))
            if gkey.strip("|"):
                by_group_key[gkey] = key
            for variant in str(row.get("name_variants") or "").split(";"):
                variant = variant.strip()
                if variant:
                    by_variant[variant.casefold()] = key

        for _, row in aliases.iterrows():
            key = str(row.get("affiliation_key") or "").strip()
            if not key:
                continue
            gkey = str(row.get("group_key") or "").strip()
            if gkey:
                by_group_key.setdefault(gkey, key)
            variant = str(row.get("affiliation_variant") or "").strip()
            if variant:
                by_variant.setdefault(variant.casefold(), key)

        redirects = {
            str(row["affiliation_key"]).strip(): str(row["redirect_to_affiliation_key"]).strip()
            for _, row in registry.iterrows()
            if str(row.get("redirect_to_affiliation_key") or "").strip()
        }

        return cls(
            registry=registry.set_index("affiliation_key", drop=False),
            by_group_key=by_group_key,
            by_variant=by_variant,
            redirects=redirects,
        )

    def follow_redirect(self, affiliation_key: str) -> str:
        seen: set[str] = set()
        while affiliation_key in self.redirects and affiliation_key not in seen:
            seen.add(affiliation_key)
            affiliation_key = self.redirects[affiliation_key]
        return affiliation_key

    def resolve_key(self, organisation: str, country: str = "") -> str:
        organisation = str(organisation or "").strip()
        country = str(country or "").strip()
        if not organisation:
            return ""

        gkey = group_key(organisation, country)
        if gkey in self.by_group_key:
            return self.follow_redirect(self.by_group_key[gkey])

        for candidate in (
            _make_affiliation(organisation, country),
            organisation,
        ):
            if not candidate:
                continue
            hit = self.by_variant.get(candidate.casefold())
            if hit:
                return self.follow_redirect(hit)

        return ""

    def resolve_row(self, organisation: str, country: str = "") -> pd.Series | None:
        key = self.resolve_key(organisation, country)
        if not key or key not in self.registry.index:
            return None
        return self.registry.loc[key]

    def is_geocoded(self, organisation: str, country: str = "") -> bool:
        row = self.resolve_row(organisation, country)
        if row is None:
            return False
        return _geocoded_status(str(row.get("geocode_status") or ""))

    def plot_on_map(self, organisation: str, country: str = "") -> bool:
        row = self.resolve_row(organisation, country)
        if row is None:
            return False
        return _geocoded_status(str(row.get("geocode_status") or "")) and _truthy(
            row.get("plot_on_map")
        )


def _truthy(value: object) -> bool:
    return str(value or "").strip().lower() in {"true", "1", "yes"}


def lookup_affiliation_key(
    organisation: str,
    country: str = "",
    *,
    index: AffiliationIndex | None = None,
) -> str:
    if index is None:
        index = AffiliationIndex.load()
    return index.resolve_key(organisation, country)


def registry_geocode_hit(
    organisation: str,
    country: str = "",
    *,
    index: AffiliationIndex | None = None,
) -> dict[str, object] | None:
    """Return coordinates from the affiliation registry when geocoded."""
    if index is None:
        index = AffiliationIndex.load()
    row = index.resolve_row(organisation, country)
    if row is None or not _geocoded_status(str(row.get("geocode_status") or "")):
        return None
    latitude = row.get("latitude")
    longitude = row.get("longitude")
    if pd.isna(latitude) or pd.isna(longitude):
        return None
    country_name = str(row.get("country") or country or "").strip()
    geocode_source = str(row.get("geocode_source") or "").strip().lower()
    geocode_status = str(row.get("geocode_status") or "").strip().lower()
    geocode_level = "country" if geocode_source == "capital_fallback" or geocode_status == "fallback" else "institute"
    formatted_address = str(row.get("canonical_affiliation") or "")
    if geocode_level == "country" and country_name:
        from src.geocoding.capital_data import lookup_country_capital

        record = lookup_country_capital(country_name)
        if record is not None:
            formatted_address = f"{record.city}, {country_name}"
    return {
        "latitude": float(latitude),
        "longitude": float(longitude),
        "geocode_level": geocode_level,
        "query_used": f"registry:{row.get('affiliation_key')}",
        "formatted_address": formatted_address,
        "country": country_name,
    }
