"""Resolve and attach registry person_key (icrs-p-*) and affiliation_key (icrs-a-*).

Keys are assigned in the registry build stages; downstream code should resolve
through this module instead of re-deriving identity from bare names.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Any

import pandas as pd

from src.registry.affiliation_lookup import AffiliationIndex, lookup_affiliation_key
from src.registry.affiliation_registry import parse_affiliation_parts
from src.registry.person_registry import (
    DEFAULT_ALIASES_PATH,
    DEFAULT_REGISTRY_PATH,
    load_name_aliases,
    load_person_registry,
)
from src.sources.delegates import (
    PRESENTER_NODE_SEP,
    delegate_org_country_for_row,
    normalize_organisation_label,
    normalize_person_name,
    organisations_likely_same,
    presenter_identity_node,
)

PERSON_KEY_COL = "person_key"
AFFILIATION_KEY_COL = "affiliation_key"


def _truthy_attended(value: object) -> bool:
    return str(value or "").strip().lower() in {"true", "1", "yes"}


def _name_keys_for_person(person: pd.Series) -> set[str]:
    keys = {normalize_person_name(str(person.get("canonical_name") or ""))}
    for variant in str(person.get("name_variants") or "").split(";"):
        variant = variant.strip()
        if variant:
            keys.add(normalize_person_name(variant))
    return {key for key in keys if key}


class RegistryKeyResolver:
    """Registry-backed person and affiliation key resolution."""

    def __init__(
        self,
        *,
        people: pd.DataFrame | None = None,
        aliases: pd.DataFrame | None = None,
        affiliation_index: AffiliationIndex | None = None,
    ) -> None:
        self.people = people if people is not None else load_person_registry(DEFAULT_REGISTRY_PATH)
        self.aliases = aliases if aliases is not None else load_name_aliases(DEFAULT_ALIASES_PATH)
        self.affiliation_index = affiliation_index or AffiliationIndex.load()
        self.people_by_key = {
            str(row["person_key"]): row for _, row in self.people.iterrows() if str(row.get("person_key") or "").strip()
        }
        self.key_to_canonical = {
            person_key: str(row.get("canonical_name") or "").strip()
            for person_key, row in self.people_by_key.items()
        }
        self.variant_to_key, self.member_to_person_key = self._build_person_caches()
        self.name_to_person_keys = self._build_name_to_person_keys()

    def _build_name_to_person_keys(self) -> dict[str, list[str]]:
        name_to_keys: dict[str, list[str]] = {}
        for person_key, person in self.people_by_key.items():
            for name_key in _name_keys_for_person(person):
                bucket = name_to_keys.setdefault(name_key, [])
                if person_key not in bucket:
                    bucket.append(person_key)
        return name_to_keys

    def _build_person_caches(self) -> tuple[dict[str, str], dict[str, str]]:
        variant_to_key: dict[str, str] = {}
        norm_to_keys: dict[str, set[str]] = {}
        for _, row in self.aliases.iterrows():
            person_key = str(row.get("person_key") or "").strip()
            if not person_key:
                continue
            for column in ("name_variant", "normalized_name"):
                variant = str(row.get(column) or "").strip()
                if not variant:
                    continue
                for key in {
                    variant,
                    variant.casefold(),
                    normalize_person_name(variant),
                }:
                    if not key:
                        continue
                    norm_to_keys.setdefault(key, set()).add(person_key)

        for key, person_keys in norm_to_keys.items():
            if len(person_keys) == 1:
                variant_to_key[key] = next(iter(person_keys))

        member_to_person_key: dict[str, str] = {}
        for person_key, person in self.people_by_key.items():
            for name_key in _name_keys_for_person(person):
                member_to_person_key[name_key] = person_key
            organisation = str(person.get("organisation") or "").strip()
            country = str(person.get("country") or "").strip()
            if organisation:
                from src.registry.affiliation_registry import _make_affiliation

                affiliation = _make_affiliation(organisation, country)
                for aff_candidate in (affiliation, organisation):
                    node = presenter_identity_node(
                        normalize_person_name(str(person.get("canonical_name") or "")),
                        aff_candidate,
                    )
                    member_to_person_key[node] = person_key
                    norm = normalize_person_name(str(person.get("canonical_name") or ""))
                    if norm:
                        member_to_person_key[
                            presenter_identity_node(norm, normalize_organisation_label(aff_candidate))
                        ] = person_key

        return variant_to_key, member_to_person_key

    def _prefer_attended_person_key(self, matches: list[str]) -> str:
        if not matches:
            return ""
        if len(matches) == 1:
            return matches[0]
        attended = [
            person_key
            for person_key in matches
            if _truthy_attended(self.people_by_key.get(person_key, {}).get("attended"))
        ]
        if len(attended) == 1:
            return attended[0]
        return ""

    def _matches_for_name_and_affiliation(
        self,
        norm: str,
        *,
        organisation: str = "",
        country: str = "",
        affiliation_text: str = "",
    ) -> list[str]:
        target_aff_key = self.resolve_affiliation_key(organisation, country)
        matches: list[str] = []
        for person_key in self.name_to_person_keys.get(norm, []):
            person = self.people_by_key[person_key]
            if target_aff_key:
                person_aff_key = self.resolve_affiliation_key(
                    str(person.get("organisation") or ""),
                    str(person.get("country") or ""),
                )
                if person_aff_key != target_aff_key:
                    continue
            else:
                person_org = str(person.get("organisation") or "").strip()
                if organisation or affiliation_text:
                    candidate_orgs = [organisation, affiliation_text]
                    if not any(
                        organisations_likely_same(person_org, candidate)
                        for candidate in candidate_orgs
                        if str(candidate or "").strip()
                    ):
                        continue
            matches.append(person_key)
        return matches

    def resolve_affiliation_key(
        self,
        organisation: str = "",
        country: str = "",
        *,
        affiliation_text: str = "",
    ) -> str:
        organisation = str(organisation or "").strip()
        country = str(country or "").strip()
        affiliation_text = str(affiliation_text or "").strip()
        if not organisation and affiliation_text:
            organisation, country = parse_affiliation_parts(affiliation_text)
        return lookup_affiliation_key(
            organisation,
            country,
            index=self.affiliation_index,
        )

    def resolve_person_key(self, name: str, *, affiliation: str = "") -> str:
        cleaned = str(name or "").strip()
        if not cleaned:
            return ""
        norm = normalize_person_name(cleaned)
        affiliation_text = str(affiliation or "").strip()

        if affiliation_text:
            org, country = parse_affiliation_parts(affiliation_text)
            matches = self._matches_for_name_and_affiliation(
                norm,
                organisation=org,
                country=country,
                affiliation_text=affiliation_text,
            )
            preferred = self._prefer_attended_person_key(matches)
            if preferred:
                return preferred

            for org_candidate in _affiliation_org_candidates(affiliation_text):
                node = presenter_identity_node(norm, org_candidate)
                person_key = self.member_to_person_key.get(node)
                if person_key:
                    return person_key
            aff_norm = normalize_organisation_label(affiliation_text)
            if aff_norm:
                prefix = f"{norm}{PRESENTER_NODE_SEP}"
                node_matches = {
                    person_key
                    for member, person_key in self.member_to_person_key.items()
                    if member.startswith(prefix)
                    and organisations_likely_same(aff_norm, member.split(PRESENTER_NODE_SEP, 1)[-1])
                }
                preferred = self._prefer_attended_person_key(sorted(node_matches))
                if preferred:
                    return preferred

        bare_matches = list(self.name_to_person_keys.get(norm, []))
        preferred = self._prefer_attended_person_key(bare_matches)
        if preferred:
            return preferred

        return (
            self.variant_to_key.get(norm)
            or self.variant_to_key.get(cleaned.casefold())
            or self.variant_to_key.get(cleaned)
            or ""
        )

    def canonical_name(self, person_key: str, *, fallback: str = "") -> str:
        person_key = str(person_key or "").strip()
        if person_key in self.key_to_canonical:
            return self.key_to_canonical[person_key]
        return fallback

    def enrich_talks(
        self,
        talks: pd.DataFrame,
        *,
        presenter_col: str = "presenter",
        affiliation_col: str = "affiliation",
    ) -> pd.DataFrame:
        if talks.empty:
            return talks.copy()
        frame = talks.copy()
        person_keys: list[str] = []
        affiliation_keys: list[str] = []
        for _, row in frame.iterrows():
            presenter = str(row.get(presenter_col) or "").strip()
            affiliation_text = str(row.get(affiliation_col) or "").strip()
            person_key = self.resolve_person_key(presenter, affiliation=affiliation_text)
            person_keys.append(person_key)
            org, country = parse_affiliation_parts(affiliation_text)
            if person_key and person_key in self.people_by_key:
                person = self.people_by_key[person_key]
                org = str(person.get("organisation") or org).strip()
                country = str(person.get("country") or country).strip()
            affiliation_keys.append(
                self.resolve_affiliation_key(org, country, affiliation_text=affiliation_text)
            )
        frame[PERSON_KEY_COL] = person_keys
        frame[AFFILIATION_KEY_COL] = affiliation_keys
        return frame

    def enrich_delegates(self, delegates: pd.DataFrame) -> pd.DataFrame:
        if delegates.empty:
            return delegates.copy()
        frame = delegates.copy()
        person_keys: list[str] = []
        affiliation_keys: list[str] = []
        for _, row in frame.iterrows():
            name = str(row.get("full_name") or "").strip()
            organisation, country = delegate_org_country_for_row(row)
            person_key = self.resolve_person_key(
                name,
                affiliation=_make_delegate_affiliation(organisation, country),
            )
            if not person_key:
                person_key = self._match_delegate_row_to_registry(name, organisation, country)
            person_keys.append(person_key)
            affiliation_keys.append(self.resolve_affiliation_key(organisation, country))
        frame[PERSON_KEY_COL] = person_keys
        frame[AFFILIATION_KEY_COL] = affiliation_keys
        return frame

    def _match_delegate_row_to_registry(
        self,
        name: str,
        organisation: str,
        country: str,
    ) -> str:
        norm = normalize_person_name(name)
        if not norm:
            return ""
        target_aff_key = self.resolve_affiliation_key(organisation, country)
        matches: list[str] = []
        for person_key, person in self.people_by_key.items():
            if norm not in _name_keys_for_person(person):
                continue
            if not _truthy_attended(person.get("attended")):
                continue
            person_aff_key = self.resolve_affiliation_key(
                str(person.get("organisation") or ""),
                str(person.get("country") or ""),
            )
            if target_aff_key and person_aff_key != target_aff_key:
                continue
            matches.append(person_key)
        if len(matches) == 1:
            return matches[0]
        return ""


def _affiliation_org_candidates(affiliation: str) -> list[str]:
    organisation, country = parse_affiliation_parts(str(affiliation or "").strip())
    candidates: list[str] = []
    if str(affiliation or "").strip():
        candidates.append(str(affiliation).strip())
    if organisation:
        candidates.append(organisation)
        if country:
            from src.registry.affiliation_registry import _make_affiliation

            candidates.append(_make_affiliation(organisation, country))
    deduped: list[str] = []
    for candidate in candidates:
        if candidate and candidate not in deduped:
            deduped.append(candidate)
    return deduped


def _make_delegate_affiliation(organisation: str, country: str) -> str:
    from src.registry.affiliation_registry import _make_affiliation

    organisation = str(organisation or "").strip()
    country = str(country or "").strip()
    if organisation and country:
        return _make_affiliation(organisation, country)
    return organisation


@lru_cache(maxsize=1)
def get_registry_key_resolver() -> RegistryKeyResolver:
    return RegistryKeyResolver()


def resolve_person_key(name: str, *, affiliation: str = "") -> str:
    return get_registry_key_resolver().resolve_person_key(name, affiliation=affiliation)


def resolve_affiliation_key(
    organisation: str = "",
    country: str = "",
    *,
    affiliation_text: str = "",
) -> str:
    return get_registry_key_resolver().resolve_affiliation_key(
        organisation,
        country,
        affiliation_text=affiliation_text,
    )


def enrich_talks_with_registry_keys(
    talks: pd.DataFrame,
    *,
    presenter_col: str = "presenter",
    affiliation_col: str = "affiliation",
    resolver: RegistryKeyResolver | None = None,
) -> pd.DataFrame:
    resolver = resolver or get_registry_key_resolver()
    return resolver.enrich_talks(
        talks,
        presenter_col=presenter_col,
        affiliation_col=affiliation_col,
    )


def enrich_delegates_with_registry_keys(
    delegates: pd.DataFrame,
    *,
    resolver: RegistryKeyResolver | None = None,
) -> pd.DataFrame:
    resolver = resolver or get_registry_key_resolver()
    return resolver.enrich_delegates(delegates)


def clear_registry_key_resolver_cache() -> None:
    get_registry_key_resolver.cache_clear()
