"""Registry-backed attendee frames for map and emissions export."""

from __future__ import annotations

import pandas as pd

from src.registry.affiliation_lookup import AffiliationIndex, registry_geocode_hit
from src.registry.affiliation_registry import _make_affiliation, parse_affiliation_parts
from src.registry.key_resolution import (
    AFFILIATION_KEY_COL,
    PERSON_KEY_COL,
    RegistryKeyResolver,
    enrich_talks_with_registry_keys,
    get_registry_key_resolver,
)
from src.registry.person_registry import DEFAULT_REGISTRY_PATH, load_person_registry
from src.sources.delegates import country_to_iso2
from src.sources.programme import load_talks


def _attended_people() -> pd.DataFrame:
    people = load_person_registry(DEFAULT_REGISTRY_PATH)
    return people.loc[
        people["attended"].astype(str).str.strip().str.lower().isin({"true", "1", "yes"})
    ].copy()


def _affiliation_for_person(person: pd.Series) -> tuple[str, str, str]:
    organisation = str(person.get("organisation") or "").strip()
    country = str(person.get("country") or "").strip()
    affiliation = _make_affiliation(organisation, country) if organisation else ""
    return organisation, country, affiliation


from src.geocoding.capital_coords import capital_geocode_hit
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
        organisation = org or organisation
        country = ctry or country
    if hit is None and country:
        hit = capital_geocode_hit(organisation, country, require=True)
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
    resolver: RegistryKeyResolver | None = None,
) -> pd.DataFrame:
    """Programme talks + attended delegates, keyed and geocoded via registries."""
    resolver = resolver or get_registry_key_resolver()
    talks = enrich_talks_with_registry_keys(load_talks(), resolver=resolver)
    attended = _attended_people()
    by_person_key = resolver.people_by_key
    index = resolver.affiliation_index

    talk_rows: list[dict[str, object]] = []
    seen_person_keys: set[str] = set()

    for _, talk in talks.iterrows():
        presenter = str(talk.get("presenter") or "").strip()
        if not presenter:
            continue
        row = talk.to_dict()
        person_key = str(row.get(PERSON_KEY_COL) or "").strip()
        affiliation_key = str(row.get(AFFILIATION_KEY_COL) or "").strip()
        if person_key:
            seen_person_keys.add(person_key)
            row[PERSON_KEY_COL] = person_key
        if affiliation_key:
            row[AFFILIATION_KEY_COL] = affiliation_key

        person = by_person_key.get(person_key) if person_key else None
        programme_affiliation = str(row.get("affiliation") or "").strip()
        organisation, country, affiliation = "", "", programme_affiliation
        if person is not None and str(person.get("attended") or "").strip().lower() in {
            "true",
            "1",
            "yes",
        }:
            organisation, country, affiliation = _affiliation_for_person(person)
            if affiliation:
                row["affiliation"] = affiliation
        if not organisation and programme_affiliation:
            organisation, country = parse_affiliation_parts(programme_affiliation)

        row["attended_only"] = False
        talk_rows.append(
            _attach_registry_geocode(
                row,
                organisation=organisation,
                country=country,
                index=index,
            )
        )

    # Attended non-presenters: keep for emissions / geocode coverage, but mark so
    # map pins and the co-authorship network do not treat them as programme speakers.
    extra_rows: list[dict[str, object]] = []
    for _, person in attended.iterrows():
        person_key = str(person.get("person_key") or "").strip()
        if not person_key or person_key in seen_person_keys:
            continue
        name = str(person.get("canonical_name") or "").strip()
        if not name:
            continue
        organisation, country, affiliation = _affiliation_for_person(person)
        if not organisation and not country:
            continue
        if not affiliation and country:
            affiliation = _make_affiliation(organisation or ".", country)
        affiliation_key = resolver.resolve_affiliation_key(organisation, country)
        row: dict[str, object] = {
            "presenter": name,
            "affiliation": affiliation,
            PERSON_KEY_COL: person_key,
            AFFILIATION_KEY_COL: affiliation_key,
            "title": pd.NA,
            "abstract": pd.NA,
            "attended_only": True,
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
