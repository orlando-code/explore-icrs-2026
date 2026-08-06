"""Registry-backed attendee frames for map and emissions export."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from src.registry.affiliation_lookup import AffiliationIndex, registry_geocode_hit
from src.registry.affiliation_registry import _make_affiliation, parse_affiliation_parts
from src.sources.delegates import country_to_iso2, normalize_person_name
from src.registry.person_registry import DEFAULT_ALIASES_PATH, DEFAULT_REGISTRY_PATH, load_person_registry
from src.sources.programme import load_talks


def _attended_people() -> pd.DataFrame:
    people = load_person_registry(DEFAULT_REGISTRY_PATH)
    attended = people.loc[
        people["attended"].astype(str).str.strip().str.lower().isin({"true", "1", "yes"})
    ].copy()
    return attended


def _person_name_lookup(attended: pd.DataFrame) -> dict[str, pd.Series]:
    lookup: dict[str, pd.Series] = {}
    aliases_path = DEFAULT_ALIASES_PATH
    if aliases_path.exists():
        aliases = pd.read_csv(aliases_path)
        alias_to_key = {
            str(row.get("normalized_name") or row.get("name_variant") or "").strip(): str(
                row.get("person_key") or ""
            ).strip()
            for _, row in aliases.iterrows()
        }
    else:
        alias_to_key = {}

    by_key = {str(row["person_key"]): row for _, row in attended.iterrows()}
    for _, person in attended.iterrows():
        keys = {normalize_person_name(str(person.get("canonical_name") or ""))}
        for variant in str(person.get("name_variants") or "").split(";"):
            variant = variant.strip()
            if variant:
                keys.add(normalize_person_name(variant))
        for key in keys:
            if key:
                lookup[key] = person

    for alias_name, person_key in alias_to_key.items():
        normalized = normalize_person_name(alias_name)
        if normalized and person_key in by_key and normalized not in lookup:
            lookup[normalized] = by_key[person_key]
    return lookup


def _affiliation_for_person(person: pd.Series) -> tuple[str, str, str]:
    organisation = str(person.get("organisation") or "").strip()
    country = str(person.get("country") or "").strip()
    affiliation = _make_affiliation(organisation, country) if organisation else ""
    return organisation, country, affiliation


def _attach_registry_geocode(
    row: dict[str, object],
    *,
    organisation: str,
    country: str,
    index: AffiliationIndex,
) -> dict[str, object]:
    hit = registry_geocode_hit(organisation, country, index=index)
    if hit is None and row.get("affiliation"):
        org, ctry = parse_affiliation_parts(str(row["affiliation"]))
        hit = registry_geocode_hit(org or organisation, ctry or country, index=index)
    if hit is None:
        return row
    row["latitude"] = hit["latitude"]
    row["longitude"] = hit["longitude"]
    row["geocode_level"] = hit.get("geocode_level")
    row["geocoded"] = True
    row["query_used"] = hit.get("query_used")
    row["country_code"] = country_to_iso2(str(hit.get("country") or country or ""))
    if hit.get("formatted_address"):
        row["formatted_address"] = hit["formatted_address"]
    return row


def build_map_talks(
    *,
    show_progress: bool = False,
) -> pd.DataFrame:
    """Programme talks + attended delegates, geocoded via affiliation registry."""
    talks = load_talks()
    attended = _attended_people()
    name_lookup = _person_name_lookup(attended)
    index = AffiliationIndex.load()

    talk_rows: list[dict[str, object]] = []
    seen_presenters: set[str] = set()

    for _, talk in talks.iterrows():
        presenter = str(talk.get("presenter") or "").strip()
        if not presenter:
            continue
        normalized = normalize_person_name(presenter)
        seen_presenters.add(normalized)
        row = talk.to_dict()
        person = name_lookup.get(normalized)
        organisation, country, affiliation = "", "", str(row.get("affiliation") or "").strip()
        if person is not None:
            organisation, country, affiliation = _affiliation_for_person(person)
            if affiliation:
                row["affiliation"] = affiliation
        if not organisation and row.get("affiliation"):
            organisation, country = parse_affiliation_parts(str(row["affiliation"]))
        talk_rows.append(
            _attach_registry_geocode(
                row,
                organisation=organisation,
                country=country,
                index=index,
            )
        )

    extra_rows: list[dict[str, object]] = []
    for _, person in attended.iterrows():
        name = str(person.get("canonical_name") or "").strip()
        if not name:
            continue
        normalized = normalize_person_name(name)
        if normalized in seen_presenters:
            continue
        organisation, country, affiliation = _affiliation_for_person(person)
        if not organisation:
            continue
        row: dict[str, object] = {
            "presenter": name,
            "affiliation": affiliation,
            "title": pd.NA,
            "abstract": pd.NA,
        }
        extra_rows.append(
            _attach_registry_geocode(
                row,
                organisation=organisation,
                country=country,
                index=index,
            )
        )

    combined = pd.DataFrame(talk_rows)
    if extra_rows:
        combined = pd.concat([combined, pd.DataFrame(extra_rows)], ignore_index=True)
    return combined
