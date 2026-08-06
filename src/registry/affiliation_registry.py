"""Build an affiliation registry with internal icrs-a-* keys."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pandas as pd

from src.sources.delegates import (
    country_to_iso2,
    load_delegates,
    normalize_person_name,
    organisation_for_delegate_row,
)
from src.geocoding.geocode import (
    affiliation_display_name,
    canonical_affiliation_key,
    load_affiliation_display_aliases,
    resolve_affiliation_alias,
    _trailing_country_part_count,
)
from src.sources.programme import load_talks
from src.data_paths import (
    AFFILIATION_ALIASES_CSV,
    AFFILIATION_GEOCODES_CSV,
    AFFILIATION_GEOCODES_MANUAL_CSV,
    AFFILIATION_REGISTRY_CSV,
    AFFILIATION_OVERRIDES_CSV,
    AFFILIATION_REVIEWED_CSV,
    AFFILIATION_UNMATCHED_CSV,
    DATA_ROOT,
    DELEGATES_JSON,
    GEOCODE_OVERRIDES_JSON,
    PERSON_REGISTRY_CSV,
    PROGRAMME_JSON,
    ABSTRACTS_JSON,
)

DEFAULT_REGISTRY_PATH = AFFILIATION_REGISTRY_CSV
DEFAULT_ALIASES_PATH = AFFILIATION_ALIASES_CSV
DEFAULT_UNMATCHED_PATH = AFFILIATION_UNMATCHED_CSV
DEFAULT_REVIEWED_PATH = AFFILIATION_REVIEWED_CSV
DEFAULT_OVERRIDES_PATH = AFFILIATION_OVERRIDES_CSV
DEFAULT_GEOCODE_OVERRIDES_JSON = GEOCODE_OVERRIDES_JSON
DEFAULT_PERSON_REGISTRY_PATH = PERSON_REGISTRY_CSV

AFFILIATION_KEY_PREFIX = "icrs-a-"


@dataclass
class AffiliationRecord:
    affiliation_key: str
    canonical_affiliation: str
    organisation: str
    country: str
    country_code: str = ""
    geocode_status: str = "missing"
    latitude: str = ""
    longitude: str = ""
    geocode_source: str = ""
    variant_count: int = 0
    attendee_count: int = 0
    in_delegate_list: bool = False
    in_programme: bool = False
    sources: list[str] = field(default_factory=list)
    name_variants: list[str] = field(default_factory=list)
    needs_review: bool = False
    review_reason: str = ""
    primary_organisation: str = ""
    secondary_organisation: str = ""
    redirect_to_affiliation_key: str = ""
    plot_on_map: bool = True

    def to_row(self) -> dict[str, Any]:
        return {
            "affiliation_key": self.affiliation_key,
            "canonical_affiliation": self.canonical_affiliation,
            "organisation": self.organisation,
            "country": self.country,
            "country_code": self.country_code,
            "geocode_status": self.geocode_status,
            "latitude": self.latitude,
            "longitude": self.longitude,
            "geocode_source": self.geocode_source,
            "variant_count": self.variant_count,
            "attendee_count": self.attendee_count,
            "in_delegate_list": self.in_delegate_list,
            "in_programme": self.in_programme,
            "sources": ";".join(sorted(set(self.sources))),
            "name_variants": "; ".join(sorted(set(self.name_variants))),
            "needs_review": self.needs_review,
            "review_reason": self.review_reason,
            "primary_organisation": self.primary_organisation,
            "secondary_organisation": self.secondary_organisation,
            "redirect_to_affiliation_key": self.redirect_to_affiliation_key,
            "plot_on_map": self.plot_on_map,
        }


@dataclass
class AffiliationBuildResult:
    registry: pd.DataFrame
    aliases: pd.DataFrame
    unmatched: pd.DataFrame
    metrics: dict[str, Any] = field(default_factory=dict)


def _read_csv(path: Path) -> pd.DataFrame:
    return pd.read_csv(path, dtype=str, encoding="utf-8", encoding_errors="replace").fillna("")


def _make_affiliation(organisation: str, country: str) -> str:
    org = str(organisation or "").strip()
    country = str(country or "").strip()
    if not org:
        return ""
    return f"{org}, {country}" if country else org


def _is_valid_country(country: str) -> bool:
    return bool(str(country or "").strip()) and bool(country_to_iso2(country))


def parse_affiliation_parts(affiliation: str) -> tuple[str, str]:
    """Split an affiliation string into organisation and country.

    Uses country-code validation on trailing comma-separated segments so org
    names may contain commas (e.g. "Rethinking, Rebuilding, Regenerating Coral
    Reefs, Philippines").
    """
    text = str(affiliation or "").strip()
    if not text:
        return "", ""
    parts = [part.strip() for part in text.split(",") if part.strip()]
    if not parts:
        return "", ""
    if len(parts) == 1:
        return parts[0], ""

    trailing = _trailing_country_part_count(parts)
    if trailing:
        organisation = ", ".join(parts[:-trailing]).strip()
        country = ", ".join(parts[-trailing:]).strip()
        return organisation, country

    return ", ".join(parts), ""


def _build_delegate_affiliation_index(delegates: pd.DataFrame) -> dict[str, tuple[str, str]]:
    """Map affiliation strings and variants to authoritative org/country from delegates."""
    index: dict[str, tuple[str, str]] = {}
    for _, row in delegates.iterrows():
        organisation = organisation_for_delegate_row(row)
        country = str(row.get("country") or "").strip()
        if not organisation or not _is_valid_country(country):
            continue
        pair = (organisation, country)
        keys = {
            str(row.get("affiliation") or "").strip().casefold(),
            _make_affiliation(organisation, country).casefold(),
            organisation.casefold(),
            group_key(organisation, country),
        }
        for key in keys:
            if key:
                index[key] = pair
    return index


def _resolve_org_country(
    organisation: str,
    country: str,
    *,
    affiliation: str = "",
    delegate_index: dict[str, tuple[str, str]] | None = None,
) -> tuple[str, str]:
    """Normalise organisation/country using delegate authority and smart parsing."""
    organisation = str(organisation or "").strip()
    country = str(country or "").strip()
    affiliation = str(affiliation or "").strip()

    if delegate_index:
        for key in (
            affiliation.casefold(),
            _make_affiliation(organisation, country).casefold(),
            group_key(organisation, country),
        ):
            if key and key in delegate_index:
                return delegate_index[key]

    if organisation and _is_valid_country(country):
        return organisation, country

    for candidate in (affiliation, _make_affiliation(organisation, country), organisation):
        if not candidate:
            continue
        parsed_org, parsed_country = parse_affiliation_parts(candidate)
        if parsed_org and _is_valid_country(parsed_country):
            if delegate_index:
                hit = delegate_index.get(_make_affiliation(parsed_org, parsed_country).casefold())
                if hit:
                    return hit
                hit = delegate_index.get(parsed_org.casefold())
                if hit:
                    return hit
            return parsed_org, parsed_country

    return organisation, country


def _parse_affiliation_text(affiliation: str) -> tuple[str, str]:
    return parse_affiliation_parts(affiliation)


def group_key(organisation: str, country: str) -> str:
    """Stable merge key for one institution in one country."""
    org = resolve_affiliation_alias(str(organisation or "").strip())
    canonical_org = re.sub(r"\s+", " ", canonical_affiliation_key(org)).strip()
    country_norm = str(country or "").strip().casefold()
    return f"{canonical_org.casefold()}|{country_norm}"


def canonical_for_parts(organisation: str, country: str) -> str:
    org = resolve_affiliation_alias(str(organisation or "").strip())
    canonical_org = canonical_affiliation_key(org)
    country = str(country or "").strip()
    if country:
        return affiliation_display_name(f"{canonical_org}, {country}") or _make_affiliation(
            canonical_org, country
        )
    return affiliation_display_name(canonical_org) or canonical_org


def load_registry_overrides(path: Path | str = DEFAULT_OVERRIDES_PATH) -> pd.DataFrame:
    path = Path(path)
    columns = ["action", "left", "right", "canonical_affiliation", "notes"]
    if not path.exists():
        return pd.DataFrame(columns=columns)
    frame = _read_csv(path)
    return frame.reindex(columns=columns, fill_value="")


def _geocode_row_for_parts(
    organisation: str,
    country: str,
    *,
    lookup: dict[str, Any],
    override_lookup: dict[str, dict[str, Any]],
) -> dict[str, str]:
    from src.geocoding.affiliation_geocodes import resolve_geocode

    affiliation = _make_affiliation(organisation, country)
    hit = resolve_geocode(
        affiliation,
        presenter="",
        lookup=lookup,
        overrides=override_lookup,
    )
    if hit is None:
        return {
            "geocode_status": "missing",
            "latitude": "",
            "longitude": "",
            "geocode_source": "",
        }

    query = str(hit.get("query_used") or "")
    if query.startswith("override"):
        source = "override"
        status = "ok"
    elif query.startswith("fallback:capital"):
        source = "capital_fallback"
        status = "fallback"
    elif query.startswith("google:"):
        source = "google_csv"
        status = "ok"
    else:
        source = "geocode_csv"
        status = "ok" if hit.get("geocoded") else "failed"

    return {
        "geocode_status": status,
        "latitude": str(hit.get("latitude") or ""),
        "longitude": str(hit.get("longitude") or ""),
        "geocode_source": source,
    }


def _collect_variant_rows() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []

    def add(
        organisation: str,
        country: str,
        *,
        variant: str = "",
        source: str,
    ) -> None:
        organisation = str(organisation or "").strip()
        country = str(country or "").strip()
        if not organisation:
            return
        affiliation = variant.strip() or _make_affiliation(organisation, country)
        rows.append(
            {
                "organisation": organisation,
                "country": country,
                "affiliation_variant": affiliation,
                "source": source,
                "group_key": group_key(organisation, country),
            }
        )

    delegates = load_delegates(json_path=DELEGATES_JSON)
    delegate_index = _build_delegate_affiliation_index(delegates)

    for _, row in delegates.iterrows():
        organisation = organisation_for_delegate_row(row)
        country = str(row.get("country") or "").strip()
        affiliation = str(row.get("affiliation") or "").strip()
        organisation, country = _resolve_org_country(
            organisation,
            country,
            affiliation=affiliation,
            delegate_index=delegate_index,
        )
        add(organisation, country, variant=affiliation or _make_affiliation(organisation, country), source="delegate_list")

    talks = load_talks(PROGRAMME_JSON, ABSTRACTS_JSON)
    delegate_lookup: dict[str, tuple[str, str]] = {}
    for _, row in delegates.iterrows():
        organisation = organisation_for_delegate_row(row)
        country = str(row.get("country") or "").strip()
        if not organisation or not _is_valid_country(country):
            continue
        for name_key in {
            normalize_person_name(str(row.get("full_name") or "")),
            str(row.get("full_name") or "").strip().casefold(),
        }:
            if name_key:
                delegate_lookup[name_key] = (organisation, country)

    for _, row in talks.iterrows():
        affiliation_raw = row.get("affiliation")
        if pd.isna(affiliation_raw):
            continue
        affiliation = str(affiliation_raw).strip()
        if not affiliation or affiliation.casefold() == "nan":
            continue
        organisation, country = parse_affiliation_parts(affiliation)
        presenter = str(row.get("presenter") or "").strip()
        match = delegate_lookup.get(normalize_person_name(presenter)) or delegate_lookup.get(
            presenter.casefold()
        )
        if match:
            organisation, country = match
        else:
            organisation, country = _resolve_org_country(
                organisation,
                country,
                affiliation=affiliation,
                delegate_index=delegate_index,
            )
        affiliation = _make_affiliation(organisation, country) if country else affiliation
        add(organisation, country, variant=affiliation, source="programme")

    for alias_from, alias_to in load_affiliation_display_aliases().items():
        organisation, country = _resolve_org_country(
            *parse_affiliation_parts(alias_to),
            affiliation=alias_to,
            delegate_index=delegate_index,
        )
        if organisation:
            add(organisation, country, variant=alias_from, source="display_alias")
            add(
                organisation,
                country,
                variant=alias_to,
                source="display_alias",
            )

    from src.geocoding.affiliation_geocodes import load_geocode_source_frames

    geocode_rows = load_geocode_source_frames(
        AFFILIATION_GEOCODES_CSV,
        manual_path=AFFILIATION_GEOCODES_MANUAL_CSV,
    )
    for _, row in geocode_rows.iterrows():
        organisation, country = _resolve_org_country(
            str(row.get("organisation") or ""),
            str(row.get("country") or ""),
            affiliation=str(row.get("affiliation") or ""),
            delegate_index=delegate_index,
        )
        if not organisation:
            continue
        if not _is_valid_country(country):
            continue
        add(
            organisation,
            country,
            variant=str(row.get("affiliation") or "") or _make_affiliation(organisation, country),
            source="geocode_csv",
        )

    return rows


def _clean_review_value(value: str) -> str:
    text = str(value or "").strip()
    if text.casefold() in {"", "nan", "none"}:
        return ""
    return text


def load_affiliation_review(data_root: Path | str = DATA_ROOT) -> pd.DataFrame:
    path = AFFILIATION_REVIEWED_CSV
    if not path.exists():
        return pd.DataFrame()
    return _read_csv(path)


def _attendee_counts(
    *,
    org_redirects: dict[str, tuple[str, str, str]] | None = None,
) -> dict[str, int]:
    path = PERSON_REGISTRY_CSV
    if not path.exists():
        return {}
    registry = _read_csv(path)
    attended = registry.loc[registry["attended"].astype(str).str.lower().eq("true")]
    counts: dict[str, int] = {}
    org_redirects = org_redirects or {}
    for _, row in attended.iterrows():
        organisation = str(row.get("organisation") or "").strip()
        country = str(row.get("country") or "").strip()
        organisation, country = _resolve_attendee_org_country(
            organisation, country, org_redirects
        )
        key = group_key(organisation, country)
        counts[key] = counts.get(key, 0) + 1
    return counts


def _resolve_attendee_org_country(
    organisation: str,
    country: str,
    org_redirects: dict[str, tuple[str, str, str]],
) -> tuple[str, str]:
    organisation = str(organisation or "").strip()
    country = str(country or "").strip()
    if not org_redirects:
        return organisation, country

    keys = {
        canonical_affiliation_key(organisation).casefold(),
        organisation.casefold(),
    }
    for key in keys:
        if key in org_redirects:
            primary, review_country, _secondary = org_redirects[key]
            return primary, review_country or country

    org_canonical = canonical_affiliation_key(organisation).casefold()
    for compound_key, (primary, review_country, _secondary) in org_redirects.items():
        if compound_key in org_canonical:
            return primary, review_country or country
    return organisation, country


def _build_org_redirects(reviews: pd.DataFrame) -> dict[str, tuple[str, str, str]]:
    redirects: dict[str, tuple[str, str, str]] = {}
    for _, row in reviews.iterrows():
        secondary = _clean_review_value(row.get("secondary organisation"))
        if not secondary:
            continue
        primary = _clean_review_value(row.get("primary organisation")) or _clean_review_value(
            row.get("organisation")
        )
        country = _clean_review_value(row.get("country"))
        if not primary:
            continue
        for org in (
            _clean_review_value(row.get("organisation")),
            _clean_review_value(row.get("canonical_affiliation")),
        ):
            if not org:
                continue
            payload = (primary, country, secondary)
            redirects[canonical_affiliation_key(org).casefold()] = payload
            redirects[org.casefold()] = payload
    return redirects


def _build_primary_org_keys(reviews: pd.DataFrame) -> set[str]:
    primary_orgs: set[str] = set()
    delegates = load_delegates(json_path=DELEGATES_JSON)
    for _, row in delegates.iterrows():
        organisation = organisation_for_delegate_row(row)
        if organisation:
            primary_orgs.add(canonical_affiliation_key(organisation).casefold())
    for _, row in reviews.iterrows():
        primary = _clean_review_value(row.get("primary organisation")) or _clean_review_value(
            row.get("organisation")
        )
        if primary:
            primary_orgs.add(canonical_affiliation_key(primary).casefold())
    return primary_orgs


def _find_record_for_parts(
    records: list[AffiliationRecord],
    organisation: str,
    country: str,
) -> AffiliationRecord | None:
    target = group_key(organisation, country)
    for record in records:
        if group_key(record.organisation, record.country) == target:
            return record
    return None


def _apply_geocode_to_record(
    record: AffiliationRecord,
    *,
    geocode_lookup: dict[str, Any],
    override_lookup: dict[str, dict[str, Any]],
) -> None:
    geocode_info = _geocode_row_for_parts(
        record.organisation,
        record.country,
        lookup=geocode_lookup,
        override_lookup=override_lookup,
    )
    record.geocode_status = geocode_info["geocode_status"]
    record.latitude = geocode_info["latitude"]
    record.longitude = geocode_info["longitude"]
    record.geocode_source = geocode_info["geocode_source"]
    record.country_code = country_to_iso2(record.country)


def _review_group_keys(row: pd.Series) -> list[str]:
    keys: list[str] = []
    country = _clean_review_value(row.get("country"))
    for field in ("primary organisation", "organisation"):
        org = _clean_review_value(row.get(field))
        if not org:
            continue
        keys.append(group_key(org, country))
    return keys


def _apply_affiliation_reviews(
    records: list[AffiliationRecord],
    reviews: pd.DataFrame,
    *,
    geocode_lookup: dict[str, Any],
    override_lookup: dict[str, dict[str, Any]],
) -> dict[str, int]:
    if reviews.empty:
        return {"reviewed_rows_applied": 0}

    # Match reviews by stable org+country group_key — not affiliation_key (keys renumber).
    review_by_gkey: dict[str, pd.Series] = {}
    for _, row in reviews.iterrows():
        for gkey in _review_group_keys(row):
            if gkey.strip("|"):
                review_by_gkey[gkey] = row
                # Records with missing country use org| — match reviewed country fixes.
                org = _clean_review_value(row.get("primary organisation")) or _clean_review_value(
                    row.get("organisation")
                )
                if org and _clean_review_value(row.get("country")):
                    review_by_gkey.setdefault(group_key(org, ""), row)

    org_redirects = _build_org_redirects(reviews)
    primary_orgs = _build_primary_org_keys(reviews)
    secondary_orgs = {
        canonical_affiliation_key(_clean_review_value(row.get("secondary organisation"))).casefold()
        for _, row in reviews.iterrows()
        if _clean_review_value(row.get("secondary organisation"))
    }

    applied = 0
    compound_keys: set[str] = set()

    for record in records:
        gkey = group_key(record.organisation, record.country)
        review = review_by_gkey.get(gkey)
        if review is None and not str(record.country or "").strip():
            review = review_by_gkey.get(group_key(record.organisation, ""))
        if review is None:
            org_key = canonical_affiliation_key(record.organisation).casefold()
            redirect = org_redirects.get(org_key) or org_redirects.get(record.organisation.casefold())
            if not redirect:
                for compound_key, payload in org_redirects.items():
                    if compound_key in org_key:
                        redirect = payload
                        break
            if redirect:
                primary, country, secondary = redirect
                record.primary_organisation = primary
                record.secondary_organisation = secondary
                if country and _is_valid_country(country):
                    record.country = country
                    record.country_code = country_to_iso2(country)
                target = _find_record_for_parts(records, primary, record.country)
                if target and target.affiliation_key != record.affiliation_key:
                    record.redirect_to_affiliation_key = target.affiliation_key
                    record.plot_on_map = False
                    compound_keys.add(record.affiliation_key)
                else:
                    record.organisation = resolve_affiliation_alias(primary)
                    record.canonical_affiliation = canonical_for_parts(
                        record.organisation, record.country
                    )
                _apply_geocode_to_record(
                    record,
                    geocode_lookup=geocode_lookup,
                    override_lookup=override_lookup,
                )
                record.needs_review = False
                record.review_reason = ""
                if not _is_valid_country(record.country):
                    record.needs_review = True
                    record.review_reason = "missing_country"
                elif record.geocode_status in {"missing", "failed"}:
                    record.needs_review = True
                    record.review_reason = f"geocode_{record.geocode_status}"
            continue
        applied += 1

        primary = _clean_review_value(review.get("primary organisation")) or record.organisation
        secondary = _clean_review_value(review.get("secondary organisation"))
        country = _clean_review_value(review.get("country")) or record.country

        record.primary_organisation = primary
        record.secondary_organisation = secondary

        if country and _is_valid_country(country):
            record.country = country
            record.canonical_affiliation = canonical_for_parts(
                primary if secondary else record.organisation,
                country,
            )

        if secondary:
            compound_keys.add(record.affiliation_key)
            target = _find_record_for_parts(records, primary, country)
            if target and target.affiliation_key != record.affiliation_key:
                record.redirect_to_affiliation_key = target.affiliation_key
                record.plot_on_map = False
            else:
                record.organisation = resolve_affiliation_alias(primary)
                record.canonical_affiliation = canonical_for_parts(record.organisation, country)
                record.plot_on_map = bool(record.in_programme or record.attendee_count > 0)
        elif primary and primary != record.organisation:
            record.organisation = resolve_affiliation_alias(primary)
            record.canonical_affiliation = canonical_for_parts(record.organisation, country)

        _apply_geocode_to_record(
            record,
            geocode_lookup=geocode_lookup,
            override_lookup=override_lookup,
        )

        if country and _is_valid_country(country):
            record.needs_review = False
            record.review_reason = ""
        if not _is_valid_country(record.country):
            record.needs_review = True
            record.review_reason = record.review_reason or "missing_country"
        elif record.geocode_status in {"missing", "failed"}:
            record.needs_review = True
            record.review_reason = f"geocode_{record.geocode_status}"

    for record in records:
        if record.secondary_organisation:
            continue
        org_key = canonical_affiliation_key(record.organisation).casefold()
        if org_key in secondary_orgs and org_key not in primary_orgs:
            record.plot_on_map = False

    for record in records:
        if record.redirect_to_affiliation_key:
            continue
        if record.affiliation_key in compound_keys:
            continue
        geocoded = record.geocode_status in {"ok", "fallback"}
        record.plot_on_map = geocoded and (
            record.attendee_count > 0 or record.in_delegate_list
        )

    attendee_counts = _attendee_counts(org_redirects=org_redirects)
    for record in records:
        if record.redirect_to_affiliation_key:
            record.attendee_count = 0
            continue
        record.attendee_count = attendee_counts.get(
            group_key(record.organisation, record.country),
            0,
        )

    for record in records:
        if record.redirect_to_affiliation_key:
            continue
        geocoded = record.geocode_status in {"ok", "fallback"}
        record.plot_on_map = geocoded and (
            record.attendee_count > 0 or record.in_delegate_list or record.in_programme
        )

    return {
        "reviewed_rows_applied": applied,
        "compound_redirects": sum(1 for record in records if record.redirect_to_affiliation_key),
        "plot_on_map": sum(1 for record in records if record.plot_on_map),
        "secondary_only_hidden": sum(
            1
            for record in records
            if not record.plot_on_map
            and canonical_affiliation_key(record.organisation).casefold() in secondary_orgs
        ),
    }


def build_affiliation_registry() -> AffiliationBuildResult:
    """Build affiliation registry with internal icrs-a-* keys."""
    variant_rows = _collect_variant_rows()
    if not variant_rows:
        empty = pd.DataFrame()
        return AffiliationBuildResult(registry=empty, aliases=empty, unmatched=empty)

    variants = pd.DataFrame(variant_rows)
    attendee_counts = _attendee_counts()

    from src.geocoding.affiliation_geocodes import build_geocode_lookup, load_geocode_source_frames

    geocodes = load_geocode_source_frames(
        AFFILIATION_GEOCODES_CSV,
        manual_path=AFFILIATION_GEOCODES_MANUAL_CSV,
    )
    ok_geocodes = (
        geocodes.loc[geocodes["status"].isin(["OK", "FALLBACK"])].copy()
        if not geocodes.empty
        else geocodes
    )
    if not ok_geocodes.empty:
        ok_geocodes["latitude"] = pd.to_numeric(ok_geocodes["latitude"], errors="coerce")
        ok_geocodes["longitude"] = pd.to_numeric(ok_geocodes["longitude"], errors="coerce")
        ok_geocodes = ok_geocodes.dropna(subset=["latitude", "longitude"])

    geocode_lookup = build_geocode_lookup(ok_geocodes) if not ok_geocodes.empty else {
        "by_affiliation": {},
        "by_org_country": {},
        "by_org": {},
    }

    override_lookup: dict[str, dict[str, Any]] = {}
    if GEOCODE_OVERRIDES_JSON.exists():
        payload = json.loads(GEOCODE_OVERRIDES_JSON.read_text(encoding="utf-8"))
        override_lookup = payload if isinstance(payload, dict) else {}

    overrides = load_registry_overrides(AFFILIATION_OVERRIDES_CSV)
    canonical_overrides: dict[str, str] = {}
    merge_map: dict[str, str] = {}
    for _, row in overrides.iterrows():
        action = str(row.get("action") or "").strip().casefold()
        left = str(row.get("left") or "").strip()
        right = str(row.get("right") or "").strip()
        if action != "merge" or not left or not right:
            continue
        left_org, left_country = _parse_affiliation_text(left)
        right_org, right_country = _parse_affiliation_text(right)
        if not left_org:
            left_org = left
        if not right_org:
            right_org = right
        merge_map[group_key(left_org, left_country)] = group_key(right_org, right_country)
        canonical = str(row.get("canonical_affiliation") or "").strip()
        if canonical:
            canonical_overrides[group_key(right_org, right_country)] = canonical

    merge_map = {
        left: right for left, right in merge_map.items() if left != right
    }

    def resolve_group_key(key: str) -> str:
        while key in merge_map:
            key = merge_map[key]
        return key

    variants["group_key"] = variants["group_key"].map(resolve_group_key)

    grouped = variants.groupby("group_key", sort=True)
    group_keys = list(grouped.groups.keys())
    key_assignments = {
        group: f"{AFFILIATION_KEY_PREFIX}{index:05d}"
        for index, group in enumerate(group_keys, start=1)
    }

    records: list[AffiliationRecord] = []
    alias_rows: list[dict[str, str]] = []
    unmatched_rows: list[dict[str, str]] = []

    for gkey, frame in grouped:
        organisation = str(frame.iloc[0]["organisation"] or "").strip()
        country = str(frame.iloc[0]["country"] or "").strip()
        for _, row in frame.iterrows():
            if str(row.get("organisation") or "").strip():
                organisation = str(row["organisation"]).strip()
            if str(row.get("country") or "").strip():
                country = str(row["country"]).strip()

        canonical = canonical_overrides.get(
            gkey, canonical_for_parts(organisation, country)
        )
        geocode_info = _geocode_row_for_parts(
            organisation,
            country,
            lookup=geocode_lookup,
            override_lookup=override_lookup,
        )

        sources = sorted(set(frame["source"].astype(str)))
        name_variants = sorted(set(frame["affiliation_variant"].astype(str)) - {""})
        attendee_count = attendee_counts.get(gkey, 0)

        needs_review = False
        review_reason = ""
        if geocode_info["geocode_status"] in {"missing", "failed"}:
            needs_review = True
            review_reason = f"geocode_{geocode_info['geocode_status']}"
        if not country:
            needs_review = True
            review_reason = review_reason or "missing_country"

        record = AffiliationRecord(
            affiliation_key=key_assignments[gkey],
            canonical_affiliation=canonical,
            organisation=resolve_affiliation_alias(organisation),
            country=country,
            country_code=country_to_iso2(country),
            geocode_status=geocode_info["geocode_status"],
            latitude=geocode_info["latitude"],
            longitude=geocode_info["longitude"],
            geocode_source=geocode_info["geocode_source"],
            variant_count=len(name_variants),
            attendee_count=attendee_count,
            in_delegate_list=any(source == "delegate_list" for source in sources),
            in_programme=any(source == "programme" for source in sources),
            sources=sources,
            name_variants=name_variants,
            needs_review=needs_review,
            review_reason=review_reason,
            primary_organisation=resolve_affiliation_alias(organisation),
        )
        records.append(record)

        for variant in name_variants:
            alias_rows.append(
                {
                    "affiliation_key": record.affiliation_key,
                    "affiliation_variant": variant,
                    "group_key": gkey,
                    "source": "|".join(
                        sorted(
                            set(
                                frame.loc[
                                    frame["affiliation_variant"].eq(variant), "source"
                                ].astype(str)
                            )
                        )
                    ),
                }
            )

        if needs_review:
            unmatched_rows.append(
                {
                    "affiliation_key": record.affiliation_key,
                    "canonical_affiliation": canonical,
                    "issue": review_reason,
                    "organisation": organisation,
                    "country": country,
                    "geocode_status": record.geocode_status,
                    "attendee_count": attendee_count,
                    "name_variants": "; ".join(name_variants[:8]),
                }
            )

    reviews = load_affiliation_review()
    review_metrics: dict[str, int] = {}
    if not reviews.empty:
        review_metrics = _apply_affiliation_reviews(
            records,
            reviews,
            geocode_lookup=geocode_lookup,
            override_lookup=override_lookup,
        )
        unmatched_rows = [
            {
                "affiliation_key": record.affiliation_key,
                "canonical_affiliation": record.canonical_affiliation,
                "issue": record.review_reason,
                "organisation": record.organisation,
                "country": record.country,
                "geocode_status": record.geocode_status,
                "attendee_count": record.attendee_count,
                "name_variants": "; ".join(record.name_variants[:8]),
            }
            for record in records
            if record.needs_review
        ]
    else:
        for record in records:
            geocoded = record.geocode_status in {"ok", "fallback"}
            record.plot_on_map = geocoded and (
                record.attendee_count > 0 or record.in_delegate_list or record.in_programme
            )

    registry = pd.DataFrame(record.to_row() for record in records).sort_values("affiliation_key")
    aliases = pd.DataFrame(alias_rows).drop_duplicates().sort_values(
        ["affiliation_key", "affiliation_variant"]
    )
    unmatched = pd.DataFrame(unmatched_rows)
    if not unmatched.empty:
        unmatched = unmatched.sort_values(["issue", "canonical_affiliation"])

    geocoded = registry["geocode_status"].isin(["ok", "fallback"]).sum()
    metrics = {
        "affiliations_total": len(registry),
        "unique_variants": len(aliases),
        "in_delegate_list": int(registry["in_delegate_list"].astype(bool).sum()),
        "in_programme": int(registry["in_programme"].astype(bool).sum()),
        "with_attendees": int((registry["attendee_count"].astype(int) > 0).sum()),
        "geocoded_ok_or_fallback": int(geocoded),
        "geocode_missing_or_failed": int(registry["needs_review"].astype(str).str.lower().eq("true").sum()),
        "plot_on_map": int(registry["plot_on_map"].astype(str).str.lower().eq("true").sum()),
        "display_aliases_applied": len(load_affiliation_display_aliases()),
        "geocode_override_pins": len(override_lookup),
    }
    metrics.update(review_metrics)
    metrics["geocode_coverage_pct"] = round(
        100.0 * metrics["geocoded_ok_or_fallback"] / max(metrics["affiliations_total"], 1),
        2,
    )

    return AffiliationBuildResult(
        registry=registry,
        aliases=aliases,
        unmatched=unmatched,
        metrics=metrics,
    )


def save_affiliation_registry(
    result: AffiliationBuildResult,
    *,
    registry_path: Path | str = DEFAULT_REGISTRY_PATH,
    aliases_path: Path | str = DEFAULT_ALIASES_PATH,
    unmatched_path: Path | str = DEFAULT_UNMATCHED_PATH,
) -> dict[str, Path]:
    outputs = {
        "registry": Path(registry_path),
        "aliases": Path(aliases_path),
        "unmatched": Path(unmatched_path),
    }
    for path in outputs.values():
        path.parent.mkdir(parents=True, exist_ok=True)
    result.registry.to_csv(outputs["registry"], index=False)
    result.aliases.to_csv(outputs["aliases"], index=False)
    result.unmatched.to_csv(outputs["unmatched"], index=False)
    meta_path = outputs["registry"].with_suffix(".meta.json")
    meta_path.write_text(
        json.dumps(result.metrics, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    outputs["meta"] = meta_path
    return outputs


def load_affiliation_registry(path: Path | str = DEFAULT_REGISTRY_PATH) -> pd.DataFrame:
    return _read_csv(path)


def lookup_affiliation_key(
    organisation: str,
    country: str = "",
    *,
    aliases: pd.DataFrame | None = None,
    registry: pd.DataFrame | None = None,
) -> str:
    from src.registry.affiliation_lookup import AffiliationIndex

    if registry is None and aliases is None:
        return AffiliationIndex.load().resolve_key(organisation, country)
    if registry is None:
        registry = load_affiliation_registry()
    if aliases is None:
        aliases = _read_csv(DEFAULT_ALIASES_PATH)
    return AffiliationIndex.from_frames(registry, aliases).resolve_key(organisation, country)
