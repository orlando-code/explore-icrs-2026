"""Build a person registry with internal keys separate from official delegate IDs."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pandas as pd

from src.sources.delegates import (
    _UnionFind,
    _match_single_presenter_norm,
    delegate_identity_node,
    delegate_org_country_for_row,
    link_delegates_to_programme_talks,
    load_delegates,
    match_delegate_to_presenter_node,
    name_tokens,
    normalize_person_name,
    register_talk_presenters,
)
from src.registry.affiliation_registry import _make_affiliation
from src.registry.check_in_attendance import (
    apply_check_in_attendance,
    PUBLIC_REGISTRY_EXTRA_COLUMNS,
)
from src.sources.programme import load_talks

from src.data_paths import (
    ABSTRACTS_JSON,
    AFFILIATION_ALIASES_CSV,
    AFFILIATION_DISPLAY_ALIASES_JSON,
    AFFILIATION_GEOCODES_CSV,
    AFFILIATION_GEOCODES_MANUAL_CSV,
    AFFILIATION_REGISTRY_CSV,
    AFFILIATION_REVIEWED_CSV,
    AFFILIATION_UNMATCHED_CSV,
    DATA_ROOT,
    DELEGATES_JSON,
    GEOCODE_OVERRIDES_JSON,
    OVERRIDES,
    PERSON_ALIASES_CSV,
    PERSON_OFFICIAL_IDS_CSV,
    CHECK_IN_DELEGATES_CSV,
    PERSON_REGISTRY_CSV,
    PERSON_OVERRIDES_CSV,
    PERSON_UNMATCHED_CSV,
    PROGRAMME_JSON,
    REGISTRY,
    SOURCES,
    delegate_id_match_review_files,
)

DEFAULT_REGISTRY_PATH = PERSON_REGISTRY_CSV
DEFAULT_ALIASES_PATH = PERSON_ALIASES_CSV
DEFAULT_UNMATCHED_PATH = PERSON_UNMATCHED_CSV
DEFAULT_OVERRIDES_PATH = PERSON_OVERRIDES_CSV
DEFAULT_OFFICIAL_IDS_PATH = PERSON_OFFICIAL_IDS_CSV

PERSON_KEY_PREFIX = "icrs-p-"
PUBLIC_REGISTRY_COLUMNS = [
    "person_key",
    "canonical_name",
    "organisation",
    "country",
    "in_delegate_list",
    "in_programme",
    "attended",
    "is_speaker",
    "match_methods",
    "name_variants",
    "needs_review",
    "review_reason",
] + PUBLIC_REGISTRY_EXTRA_COLUMNS
OFFICIAL_IDS_EXPORT_COLUMNS = [
    "person_key",
    "canonical_name",
    "official_delegate_id",
    "official_id_match_tier",
]


@dataclass
class PersonRecord:
    person_key: str
    canonical_name: str
    organisation: str = ""
    country: str = ""
    in_delegate_list: bool = False
    in_programme: bool = False
    attended: bool = False
    is_speaker: bool = False
    official_delegate_id: str = ""
    official_id_match_tier: str = ""
    match_methods: list[str] = field(default_factory=list)
    name_variants: list[str] = field(default_factory=list)
    needs_review: bool = False
    review_reason: str = ""

    def to_row(self) -> dict[str, Any]:
        return {
            "person_key": self.person_key,
            "canonical_name": self.canonical_name,
            "organisation": self.organisation,
            "country": self.country,
            "in_delegate_list": self.in_delegate_list,
            "in_programme": self.in_programme,
            "attended": self.attended,
            "is_speaker": self.is_speaker,
            "official_delegate_id": self.official_delegate_id,
            "official_id_match_tier": self.official_id_match_tier,
            "match_methods": ";".join(sorted(set(self.match_methods))),
            "name_variants": "; ".join(sorted(set(self.name_variants))),
            "needs_review": self.needs_review,
            "review_reason": self.review_reason,
        }


@dataclass
class RegistryBuildResult:
    registry: pd.DataFrame
    aliases: pd.DataFrame
    unmatched: pd.DataFrame
    metrics: dict[str, Any] = field(default_factory=dict)


def _merged_review_version(path: Path) -> int:
    match = re.search(r"_(\d+)_merged\.csv$", path.name)
    return int(match.group(1)) if match else 0


def _read_review_csv(path: Path) -> pd.DataFrame:
    for encoding in ("utf-8", "utf-8-sig", "latin-1"):
        try:
            return pd.read_csv(path, dtype=str, encoding=encoding).fillna("")
        except UnicodeDecodeError:
            continue
    return pd.read_csv(path, dtype=str, encoding="latin-1").fillna("")


def load_confirmed_official_id_links(
    review_dir: Path | str = OVERRIDES,
) -> pd.DataFrame:
    """Union confirmed delegate↔official-ID name links from all merged review files.

    When the same delegate name appears in multiple merged files, the highest
    version number wins.
    """
    review_dir = Path(review_dir)
    merged_paths = delegate_id_match_review_files(review_dir)
    if not merged_paths:
        return pd.DataFrame(
            columns=[
                "delegate_full_name",
                "id_full_name",
                "delegate_id",
                "match_tier",
                "reason",
                "review_source",
            ]
        )

    frames: list[pd.DataFrame] = []
    for path in merged_paths:
        review = _read_review_csv(path)
        matched = review.loc[
            review["row_kind"].eq("delegate")
            & review["match_tier"].isin(["perfect", "confirmed"])
            & review["delegate_id"].astype(str).str.strip().ne("")
        ].copy()
        if matched.empty:
            continue
        matched["review_source"] = path.name
        frames.append(
            matched[
                [
                    "delegate_full_name",
                    "id_full_name",
                    "delegate_id",
                    "match_tier",
                    "reason",
                    "review_source",
                ]
            ]
        )

    if not frames:
        return pd.DataFrame(
            columns=[
                "delegate_full_name",
                "id_full_name",
                "delegate_id",
                "match_tier",
                "reason",
                "review_source",
            ]
        )

    combined = pd.concat(frames, ignore_index=True)
    combined["_version"] = combined["review_source"].map(
        lambda name: _merged_review_version(Path(str(name)))
    )
    combined["_delegate_norm"] = combined["delegate_full_name"].map(normalize_person_name)
    combined = combined.sort_values(["_delegate_norm", "_version"], ascending=[True, False])
    combined = combined.drop_duplicates(subset=["_delegate_norm"], keep="first")
    return combined.drop(columns=["_version", "_delegate_norm"]).reset_index(drop=True)


def _clean_official_id(value: object) -> str:
    text = str(value or "").strip()
    if not text or text.lower() == "nan":
        return ""
    if text.endswith(".0"):
        text = text[:-2]
    return text



def _ambiguous_official_id_norms(id_links: pd.DataFrame) -> set[str]:
    """id_full_name values shared by multiple delegate-list names must not bridge rows."""
    by_id_name: dict[str, set[str]] = {}
    for _, link in id_links.iterrows():
        id_norm = normalize_person_name(str(link.get("id_full_name") or ""))
        delegate_norm = normalize_person_name(str(link.get("delegate_full_name") or ""))
        if id_norm and delegate_norm:
            by_id_name.setdefault(id_norm, set()).add(delegate_norm)
    return {norm for norm, delegates in by_id_name.items() if len(delegates) > 1}


def _match_presenter_norm(
    delegate_name: str,
    token_index: dict[str, set[str]],
    presenter_display: dict[str, str],
) -> str | None:
    """Match a delegate-list name to a programme presenter without over-merging.

    Rejects token matches where the presenter name has more tokens than the
    delegate (e.g. Sam King must not match Sam King Fung Yiu).
    """
    matched = _match_single_presenter_norm(delegate_name, token_index)
    if not matched:
        return None
    delegate_tokens = name_tokens(delegate_name)
    presenter_tokens = name_tokens(presenter_display.get(matched, matched))
    if len(presenter_tokens) > len(delegate_tokens):
        return None
    return matched


def _official_id_priority(tier: str, reason: str) -> int:
    if reason == "manually_confirmed":
        return 3
    if tier == "confirmed":
        return 2
    if tier == "perfect":
        return 1
    return 0


def load_registry_overrides(path: Path | str = DEFAULT_OVERRIDES_PATH) -> pd.DataFrame:
    path = Path(path)
    columns = ["action", "left", "right", "canonical_name", "notes"]
    if not path.exists():
        return pd.DataFrame(columns=columns)
    frame = pd.read_csv(path, dtype=str, encoding="utf-8", encoding_errors="replace").fillna("")
    return frame.reindex(columns=columns, fill_value="")


def _apply_registry_overrides(
    uf: _UnionFind,
    overrides: pd.DataFrame,
    *,
    presenter_display: dict[str, str],
    delegate_display: dict[str, str],
    key_to_canonical: dict[str, str],
) -> None:
    for _, row in overrides.iterrows():
        action = str(row.get("action") or "").strip().casefold()
        left = str(row.get("left") or "").strip()
        right = str(row.get("right") or "").strip()
        if not action or not left or not right:
            continue
        left_norm = normalize_person_name(left)
        right_norm = normalize_person_name(right)
        if action == "merge":
            uf.find(left_norm)
            uf.find(right_norm)
            uf.union(left_norm, right_norm)
            canonical = str(row.get("canonical_name") or "").strip()
            if canonical:
                key_to_canonical[left_norm] = canonical
                key_to_canonical[right_norm] = canonical
        elif action == "split":
            # Split is handled by preventing union; explicit pairs are documented only.
            continue


def _assign_person_keys(components: list[set[str]], *, seed_order: dict[str, int]) -> dict[int, str]:
    def sort_key(members: set[str]) -> tuple[int, str]:
        seeds = [seed_order.get(member, 10_000_000) for member in members]
        return (min(seeds), sorted(members)[0])

    ordered = sorted(components, key=sort_key)
    return {id(members): f"{PERSON_KEY_PREFIX}{index:05d}" for index, members in enumerate(ordered, start=1)}


def build_person_registry(
    *,
    delegates: pd.DataFrame | None = None,
    talks: pd.DataFrame | None = None,
) -> RegistryBuildResult:
    """Build person registry with internal icrs-p-* keys.

    Internal person_key is our pipeline source of truth. official_delegate_id is
    optional metadata from the offset-registration ID database.
    """
    if delegates is None:
        delegates = load_delegates(json_path=DELEGATES_JSON)
    if talks is None:
        talks = load_talks(PROGRAMME_JSON, ABSTRACTS_JSON)

    uf = _UnionFind()
    presenter_display: dict[str, str] = {}
    delegate_display: dict[str, str] = {}
    delegate_meta: dict[str, dict[str, Any]] = {}
    delegation_node_by_full_name: dict[str, str] = {}
    seed_order: dict[str, int] = {}
    canonical_override: dict[str, str] = {}

    token_index: dict[str, set[str]] = {}
    register_talk_presenters(
        talks,
        presenter_display=presenter_display,
        uf=uf,
        token_index=token_index,
    )

    for index, row in delegates.iterrows():
        full_name = str(row.get("full_name") or "").strip()
        if not full_name:
            continue
        norm = str(row.get("norm_name") or normalize_person_name(full_name))
        organisation, country = delegate_org_country_for_row(row)
        affiliation = _make_affiliation(organisation, country) if organisation else ""
        delegation_node = delegate_identity_node(
            full_name,
            organisation,
            country=country,
        )
        delegate_display[delegation_node] = full_name
        delegation_node_by_full_name[full_name] = delegation_node
        delegate_meta[delegation_node] = {
            "organisation": organisation,
            "country": country,
            "is_speaker": bool(row.get("is_speaker")),
            "delegate_index": int(index),
        }
        seed_order[delegation_node] = int(index)
        uf.find(delegation_node)

        matched_presenter = match_delegate_to_presenter_node(
            full_name,
            organisation,
            token_index,
            presenter_display,
        )
        if matched_presenter:
            uf.union(delegation_node, matched_presenter)

    link_delegates_to_programme_talks(talks, delegates, uf=uf)

    id_links = load_confirmed_official_id_links(OVERRIDES)
    official_id_by_node: dict[str, tuple[str, str, str]] = {}
    # Alternate spellings from the ID database are aliases only — never programme presenters.
    official_name_display: dict[str, str] = {}
    ambiguous_id_norms = _ambiguous_official_id_norms(id_links)
    for _, link in id_links.iterrows():
        official_id = _clean_official_id(link.get("delegate_id"))
        if not official_id:
            continue
        tier = str(link.get("match_tier") or "").strip()
        reason = str(link.get("reason") or "").strip()
        delegate_name = str(link.get("delegate_full_name") or "").strip()
        delegate_norm = normalize_person_name(delegate_name)
        if not delegate_norm:
            continue
        delegation_node = delegation_node_by_full_name.get(delegate_name)
        if not delegation_node:
            continue
        uf.find(delegation_node)
        official_id_by_node[delegation_node] = (official_id, tier, reason)
        if reason == "manually_confirmed" and delegate_name:
            canonical_override[delegation_node] = delegate_name

        id_name = str(link.get("id_full_name") or "").strip()
        id_norm = normalize_person_name(id_name)
        if id_norm and id_norm != delegate_norm and id_norm not in ambiguous_id_norms:
            official_name_display.setdefault(id_norm, id_name)
            uf.find(id_norm)
            uf.union(delegation_node, id_norm)

    overrides = load_registry_overrides(DEFAULT_OVERRIDES_PATH)
    _apply_registry_overrides(
        uf,
        overrides,
        presenter_display=presenter_display,
        delegate_display=delegate_display,
        key_to_canonical=canonical_override,
    )

    components_map: dict[str, set[str]] = {}
    for node in uf.parent:
        components_map.setdefault(uf.find(node), set()).add(node)

    components = list(components_map.values())
    component_keys = _assign_person_keys(components, seed_order=seed_order)
    norm_to_person_key = {
        norm: component_keys[id(members)]
        for members in components
        for norm in members
    }

    records: dict[str, PersonRecord] = {}
    alias_rows: list[dict[str, str]] = []
    unmatched_rows: list[dict[str, str]] = []

    for members in components:
        person_key = component_keys[id(members)]
        presenter_members = sorted(member for member in members if member in presenter_display)
        delegate_members = sorted(member for member in members if member in delegate_display)
        official_members = sorted(member for member in members if member in official_name_display)

        override_names = sorted(
            {canonical_override[member] for member in members if member in canonical_override}
        )
        if override_names:
            canonical = override_names[0]
        elif presenter_members:
            canonical = presenter_display[presenter_members[0]]
        elif delegate_members:
            canonical = delegate_display[delegate_members[0]]
        elif official_members:
            canonical = official_name_display[official_members[0]]
        else:
            canonical = sorted(members)[0]

        organisation = ""
        country = ""
        is_speaker = False
        if delegate_members:
            scored_members = []
            for member in delegate_members:
                score = 0
                if member in canonical_override:
                    score += 10
                if member in official_id_by_node:
                    _, tier, reason = official_id_by_node[member]
                    score += _official_id_priority(tier, reason)
                scored_members.append(
                    (score, delegate_meta[member]["delegate_index"], member)
                )
            primary_delegate = max(scored_members)[2]
            meta = delegate_meta[primary_delegate]
            organisation = meta["organisation"]
            country = meta["country"]
            is_speaker = meta["is_speaker"]

        official_candidates = [
            (
                _official_id_priority(official_id_by_node[member][1], official_id_by_node[member][2]),
                official_id_by_node[member][0],
                official_id_by_node[member][1],
            )
            for member in delegate_members
            if member in official_id_by_node
        ]
        official_delegate_id = ""
        official_tier = ""
        if official_candidates:
            official_candidates.sort(reverse=True)
            official_delegate_id = official_candidates[0][1]
            official_tier = official_candidates[0][2]

        in_programme = bool(presenter_members)
        in_delegate_list = bool(delegate_members)
        attended = False

        methods: list[str] = []
        if presenter_members and delegate_members:
            methods.append("presenter_delegate_linked")
        elif presenter_members:
            methods.append("programme_only")
        elif delegate_members:
            methods.append("delegate_list_only")

        if any(member in official_id_by_node for member in members):
            methods.append("official_id_review")
        if any(member in canonical_override for member in members):
            methods.append("manual_canonical")

        needs_review = False
        review_reason = ""
        unresolved_official_ids = {item[1] for item in official_candidates}
        if len(unresolved_official_ids) > 1:
            top_priority = official_candidates[0][0] if official_candidates else 0
            top_ids = {item[1] for item in official_candidates if item[0] == top_priority}
            if len(top_ids) > 1:
                needs_review = True
                review_reason = "conflicting_official_delegate_ids"

        variants = {
            presenter_display[member]
            for member in presenter_members
        } | {
            delegate_display[member]
            for member in delegate_members
        } | {
            official_name_display[member]
            for member in official_members
        }
        presenter_norms = {
            normalize_person_name(presenter_display[member]) for member in presenter_members
        }
        delegate_norms = {
            normalize_person_name(delegate_display[member]) for member in delegate_members
        }
        official_norms = {
            normalize_person_name(official_name_display[member]) for member in official_members
        }

        record = PersonRecord(
            person_key=person_key,
            canonical_name=canonical,
            organisation=organisation,
            country=country,
            in_delegate_list=in_delegate_list,
            in_programme=in_programme,
            attended=attended,
            is_speaker=is_speaker,
            official_delegate_id=official_delegate_id,
            official_id_match_tier=official_tier,
            match_methods=methods,
            name_variants=sorted(variants),
            needs_review=needs_review,
            review_reason=review_reason,
        )
        records[person_key] = record

        for variant in variants:
            variant_norm = normalize_person_name(variant)
            in_presenter = variant_norm in presenter_norms
            in_delegate = variant_norm in delegate_norms
            in_official = variant_norm in official_norms
            if in_presenter and in_delegate:
                source = "both"
            elif in_presenter:
                source = "programme"
            elif in_delegate:
                source = "delegate_list"
            elif in_official:
                source = "official_id"
            else:
                source = "both"
            alias_rows.append(
                {
                    "person_key": person_key,
                    "name_variant": variant,
                    "normalized_name": variant_norm,
                    "source": source,
                }
            )

        if needs_review:
            unmatched_rows.append(
                {
                    "person_key": person_key,
                    "canonical_name": canonical,
                    "issue": review_reason,
                    "attended": attended,
                    "in_programme": in_programme,
                    "official_delegate_id": official_delegate_id,
                    "name_variants": "; ".join(sorted(variants)),
                }
            )
        elif in_programme and not attended:
            unmatched_rows.append(
                {
                    "person_key": person_key,
                    "canonical_name": canonical,
                    "issue": "programme_only_not_attended",
                    "attended": attended,
                    "in_programme": in_programme,
                    "official_delegate_id": official_delegate_id,
                    "name_variants": "; ".join(sorted(variants)),
                }
            )

    registry = pd.DataFrame(record.to_row() for record in records.values()).sort_values(
        "person_key"
    )
    aliases = pd.DataFrame(alias_rows).drop_duplicates().sort_values(
        ["person_key", "normalized_name"]
    )
    unmatched = pd.DataFrame(unmatched_rows)

    registry, aliases, check_in_metrics = apply_check_in_attendance(
        registry,
        aliases,
        check_in_path=CHECK_IN_DELEGATES_CSV,
        official_ids_path=DEFAULT_OFFICIAL_IDS_PATH,
    )

    programme_only_not_attended = registry.loc[
        registry["in_programme"].astype(str).str.strip().str.lower().isin({"true", "1", "yes"})
        & ~registry["attended"].astype(str).str.strip().str.lower().isin({"true", "1", "yes"})
    ]
    if not unmatched.empty:
        unmatched = unmatched.loc[~unmatched["issue"].eq("programme_only_not_attended")].copy()
    extra_unmatched: list[dict[str, Any]] = []
    for _, person in programme_only_not_attended.iterrows():
        extra_unmatched.append(
            {
                "person_key": person["person_key"],
                "canonical_name": person["canonical_name"],
                "issue": "programme_only_not_attended",
                "attended": person["attended"],
                "in_programme": person["in_programme"],
                "official_delegate_id": person.get("official_delegate_id", ""),
                "name_variants": person.get("name_variants", ""),
            }
        )
    if extra_unmatched:
        unmatched = pd.concat(
            [unmatched, pd.DataFrame(extra_unmatched)], ignore_index=True
        )
    if not unmatched.empty:
        unmatched = unmatched.sort_values(["issue", "canonical_name"])

    metrics = {
        "people_total": len(registry),
        "in_delegate_list": int(registry["in_delegate_list"].sum()),
        "attended": int(registry["attended"].sum()),
        "in_programme": int(registry["in_programme"].sum()),
        "linked_presenter_delegate": int(
            (registry["in_delegate_list"].astype(bool) & registry["in_programme"].astype(bool)).sum()
        ),
        "programme_only_not_attended": int(
            (registry["in_programme"].astype(bool) & ~registry["attended"].astype(bool)).sum()
        ),
        "delegate_only": int(
            (registry["attended"].astype(bool) & ~registry["in_programme"].astype(bool)).sum()
        ),
        "with_official_delegate_id": int(registry["official_delegate_id"].astype(str).str.strip().ne("").sum()),
        "without_official_delegate_id": int(registry["official_delegate_id"].astype(str).str.strip().eq("").sum()),
        "needs_review": int(registry["needs_review"].sum()),
        "name_aliases": len(aliases),
        "id_review_links_loaded": len(id_links),
        **check_in_metrics,
    }
    metrics["presenter_delegate_link_pct"] = round(
        100.0
        * metrics["linked_presenter_delegate"]
        / max(metrics["in_programme"], 1),
        2,
    )

    return RegistryBuildResult(
        registry=registry,
        aliases=aliases,
        unmatched=unmatched,
        metrics=metrics,
    )


def save_person_registry(
    result: RegistryBuildResult,
    *,
    registry_path: Path | str = DEFAULT_REGISTRY_PATH,
    aliases_path: Path | str = DEFAULT_ALIASES_PATH,
    unmatched_path: Path | str = DEFAULT_UNMATCHED_PATH,
    official_ids_path: Path | str = DEFAULT_OFFICIAL_IDS_PATH,
) -> dict[str, Path]:
    outputs = {
        "registry": Path(registry_path),
        "aliases": Path(aliases_path),
        "unmatched": Path(unmatched_path),
        "official_ids": Path(official_ids_path),
    }
    for path in outputs.values():
        path.parent.mkdir(parents=True, exist_ok=True)

    registry = result.registry.copy()
    official_id_mask = registry["official_delegate_id"].astype(str).str.strip().ne("")
    if "official_id_match_tier" in registry.columns:
        official_id_mask &= ~registry["official_id_match_tier"].astype(str).str.strip().eq(
            "check_in_only"
        )
    official_ids = registry.loc[official_id_mask, OFFICIAL_IDS_EXPORT_COLUMNS].copy()
    official_ids.to_csv(outputs["official_ids"], index=False)

    public_registry = registry.reindex(columns=PUBLIC_REGISTRY_COLUMNS)
    public_registry.to_csv(outputs["registry"], index=False)

    result.aliases.to_csv(outputs["aliases"], index=False)

    unmatched = result.unmatched.copy()
    if "official_delegate_id" in unmatched.columns:
        unmatched = unmatched.drop(columns=["official_delegate_id"])
    unmatched.to_csv(outputs["unmatched"], index=False)

    meta_path = outputs["registry"].with_suffix(".meta.json")
    meta_path.write_text(
        json.dumps(result.metrics, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    outputs["meta"] = meta_path
    return outputs


def load_person_registry(path: Path | str = DEFAULT_REGISTRY_PATH) -> pd.DataFrame:
    return pd.read_csv(path, dtype=str).fillna("")


def load_official_delegate_ids(
    path: Path | str = DEFAULT_OFFICIAL_IDS_PATH,
) -> pd.DataFrame:
    """Load local-only official delegate IDs (gitignored)."""
    official_path = Path(path)
    if not official_path.exists():
        return pd.DataFrame(columns=OFFICIAL_IDS_EXPORT_COLUMNS)
    return pd.read_csv(official_path, dtype=str).fillna("")


def load_name_aliases(path: Path | str = DEFAULT_ALIASES_PATH) -> pd.DataFrame:
    return pd.read_csv(path, dtype=str).fillna("")


def lookup_person_key(name: str, aliases: pd.DataFrame | None = None) -> str:
    from src.registry.key_resolution import resolve_person_key

    cleaned = str(name or "").strip()
    if not cleaned:
        return ""
    person_key = resolve_person_key(cleaned)
    if person_key:
        return person_key
    norm = normalize_person_name(cleaned)
    if aliases is None:
        aliases = load_name_aliases()
    hits = aliases.loc[aliases["normalized_name"].eq(norm)]
    if not hits.empty:
        return str(hits.iloc[0]["person_key"])
    hits = aliases.loc[aliases["name_variant"].str.casefold().eq(cleaned.casefold())]
    if not hits.empty:
        return str(hits.iloc[0]["person_key"])
    return ""
