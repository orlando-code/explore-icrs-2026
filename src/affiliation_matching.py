"""Detect likely duplicate affiliation display names across data sources."""

from __future__ import annotations

import re
import unicodedata
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from typing import Iterable

from src.geocode import (
    _affiliation_fingerprint,
    affiliation_base_name,
    affiliation_display_name,
    canonical_affiliation_key,
)

_STOP_TOKENS = frozenset(
    {
        "the",
        "of",
        "at",
        "and",
        "&",
        "for",
        "in",
        "on",
    }
)

_JUNK_VARIANT_RE = re.compile(
    r"\s{2,}|"
    r"\b(?:Dr|Prof|Professor)\.?\s+[A-Z]|"
    r"\b[A-Z][a-z]+\s+[A-Z][a-z]+\s+[A-Z][a-z]+\s+[A-Z]",
)


def _ascii_fold(text: str) -> str:
    folded = unicodedata.normalize("NFKD", str(text or ""))
    for char in ("\u02bb", "\u02bc", "'", "'", "`", "´", "’", "ʻ", "\u2018", "\u2019"):
        folded = folded.replace(char, "")
    return folded.encode("ascii", "ignore").decode("ascii")


def affiliation_token_key(affiliation: str) -> str:
    """Loose key: fold Unicode, ignore word order and 'at' vs '-'."""
    base = affiliation_base_name(affiliation) or str(affiliation or "").strip()
    folded = _ascii_fold(base).lower()
    folded = folded.replace("–", "-").replace("—", "-")
    folded = re.sub(r"\s+at\s+", " - ", folded)
    folded = re.sub(r"[^a-z0-9]+", " ", folded)
    tokens = [token for token in folded.split() if token and token not in _STOP_TOKENS]
    return " ".join(sorted(tokens))


def affiliation_fingerprint_key(affiliation: str) -> str:
    base = affiliation_base_name(affiliation) or str(affiliation or "").strip()
    folded = _affiliation_fingerprint(base)
    folded = re.sub(r"\s+at\s+", " - ", folded)
    return folded


def _similarity(left: str, right: str) -> float:
    if not left or not right:
        return 0.0
    return SequenceMatcher(None, left, right).ratio()


def _unicode_richness(text: str) -> int:
    score = 0
    for char in text:
        if char in "ʻʼéèáàíìóòúùüñäöÄÉÈÁÀÍÌÓÒÚÙÜÑ":
            score += 2
        if ord(char) > 127:
            score += 1
    if "Hawai" in text and "Hawaii" not in text:
        score += 1
    return score


def _looks_like_junk_variant(text: str) -> bool:
    return bool(_JUNK_VARIANT_RE.search(str(text or "")))


def looks_like_junk_affiliation(text: str) -> bool:
    return _looks_like_junk_variant(text)


def suggest_canonical_variant(variants: Iterable[str], counts: Counter[str]) -> str:
    """Pick the best display label for a duplicate cluster."""
    variant_list = list(variants)
    hyphen_variants = [variant for variant in variant_list if re.search(r"\s[-–]\s", variant)]
    candidate_variants = hyphen_variants or variant_list

    ranked: list[tuple[int, int, int, str]] = []
    for variant in candidate_variants:
        display = affiliation_display_name(variant) or variant.strip()
        if not display or _looks_like_junk_variant(display):
            continue
        ranked.append(
            (
                _unicode_richness(display),
                counts.get(variant, 0),
                len(display),
                display,
            )
        )
    if not ranked:
        fallback = max(variants, key=lambda item: counts.get(item, 0))
        return affiliation_display_name(fallback) or fallback
    ranked.sort(reverse=True)
    return ranked[0][3]


@dataclass
class AffiliationRecord:
    affiliation: str
    count: int = 0
    sources: set[str] = field(default_factory=set)


@dataclass
class AffiliationCluster:
    cluster_id: str
    variants: list[str]
    records: list[AffiliationRecord]
    match_reason: str
    suggested_canonical: str

    @property
    def total_count(self) -> int:
        return sum(record.count for record in self.records)


class UnionFind:
    def __init__(self, items: Iterable[str]) -> None:
        self.parent = {item: item for item in items}

    def find(self, item: str) -> str:
        parent = self.parent[item]
        if parent != item:
            self.parent[item] = self.find(parent)
        return self.parent[item]

    def union(self, left: str, right: str) -> None:
        root_left = self.find(left)
        root_right = self.find(right)
        if root_left != root_right:
            self.parent[root_right] = root_left


def cluster_affiliations(
    records: dict[str, AffiliationRecord],
    *,
    fuzzy_threshold: float = 0.93,
) -> list[AffiliationCluster]:
    affiliations = sorted(records)
    if not affiliations:
        return []

    uf = UnionFind(affiliations)
    reasons: dict[frozenset[str], str] = {}

    fingerprint_groups: dict[str, list[str]] = defaultdict(list)
    token_groups: dict[str, list[str]] = defaultdict(list)
    for affiliation in affiliations:
        fingerprint_groups[affiliation_fingerprint_key(affiliation)].append(affiliation)
        token_groups[affiliation_token_key(affiliation)].append(affiliation)

    def link_group(members: list[str], reason: str) -> None:
        if len(members) < 2:
            return
        anchor = members[0]
        for member in members[1:]:
            uf.union(anchor, member)
            pair = frozenset({anchor, member})
            reasons[pair] = reason

    for members in fingerprint_groups.values():
        link_group(sorted(members), "fingerprint")
    for members in token_groups.values():
        link_group(sorted(members), "token_key")

    blocks: dict[str, list[str]] = defaultdict(list)
    for affiliation in affiliations:
        token_key = affiliation_token_key(affiliation)
        block = token_key[:12] or affiliation[:12].casefold()
        blocks[block].append(affiliation)

    for block_members in blocks.values():
        if len(block_members) < 2:
            continue
        ordered = sorted(block_members, key=len)
        for index, left in enumerate(ordered):
            left_fp = affiliation_fingerprint_key(left)
            for right in ordered[index + 1 :]:
                if uf.find(left) == uf.find(right):
                    continue
                right_fp = affiliation_fingerprint_key(right)
                score = max(_similarity(left_fp, right_fp), _similarity(left, right))
                if score >= fuzzy_threshold:
                    uf.union(left, right)
                    reasons[frozenset({left, right})] = f"fuzzy:{score:.2f}"

    grouped: dict[str, list[str]] = defaultdict(list)
    for affiliation in affiliations:
        grouped[uf.find(affiliation)].append(affiliation)

    clusters: list[AffiliationCluster] = []
    for cluster_index, members in enumerate(
        sorted(grouped.values(), key=lambda items: (-len(items), items[0].casefold())),
        start=1,
    ):
        if len(members) < 2:
            continue
        member_records = [records[member] for member in sorted(members)]
        counts = Counter({record.affiliation: record.count for record in member_records})
        cluster_reasons = {
            reasons[pair]
            for pair in reasons
            if pair.issubset(set(members))
        }
        match_reason = ", ".join(sorted(cluster_reasons)) or "mixed"
        clusters.append(
            AffiliationCluster(
                cluster_id=f"C{cluster_index:04d}",
                variants=sorted(members),
                records=member_records,
                match_reason=match_reason,
                suggested_canonical=suggest_canonical_variant(members, counts),
            )
        )
    return clusters
