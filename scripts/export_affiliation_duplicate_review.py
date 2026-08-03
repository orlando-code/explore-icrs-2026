#!/usr/bin/env python3
"""Export suspected duplicate affiliation names for manual review."""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import pandas as pd

from src.affiliation_matching import (
    AffiliationRecord,
    affiliation_fingerprint_key,
    affiliation_token_key,
    cluster_affiliations,
    looks_like_junk_affiliation,
)
from src.delegates import DEFAULT_DELEGATES_JSON_PATH, load_delegates, sanitize_delegate_organisation
from src.geocode import (
    DEFAULT_CACHE_PATH,
    DEFAULT_OVERRIDES_PATH,
    affiliation_base_name,
    canonical_affiliation_key,
    affiliation_display_name,
)
from src.programme import load_talks

DEFAULT_OUTPUT_PATH = PROJECT_ROOT / "data" / "affiliation_duplicate_review.csv"
DEFAULT_SUMMARY_PATH = PROJECT_ROOT / "data" / "affiliation_duplicate_summary.csv"
_JS_AFFILIATION_RE = re.compile(r'"affiliation"\s*:\s*"((?:\\.|[^"\\])*)"')


def _add_affiliation(
    store: dict[str, AffiliationRecord],
    affiliation: str,
    *,
    source: str,
    amount: int = 1,
) -> None:
    text = str(affiliation or "").strip()
    if not text:
        return
    record = store.setdefault(text, AffiliationRecord(affiliation=text))
    record.count += amount
    record.sources.add(source)


def _affiliations_from_js(path: Path, source: str) -> list[str]:
    if not path.exists():
        return []
    text = path.read_text(encoding="utf-8")
    values: list[str] = []
    for match in _JS_AFFILIATION_RE.finditer(text):
        value = json.loads(f'"{match.group(1)}"')
        if value:
            values.append(str(value).strip())
    return values


def collect_affiliation_records() -> dict[str, AffiliationRecord]:
    store: dict[str, AffiliationRecord] = {}

    talks = load_talks()
    for affiliation, count in talks["affiliation"].dropna().astype(str).value_counts().items():
        _add_affiliation(store, affiliation_base_name(affiliation) or affiliation, source="talks", amount=int(count))

    delegates = load_delegates()
    for _, row in delegates.iterrows():
        for field in ("organisation", "affiliation"):
            value = str(row.get(field) or "").strip()
            if value:
                _add_affiliation(store, value, source="delegates")
        sanitized = sanitize_delegate_organisation(
            str(row.get("organisation") or ""),
            first_name=str(row.get("first_name") or ""),
            last_name=str(row.get("last_name") or ""),
            country=str(row.get("country") or ""),
        )
        if sanitized:
            _add_affiliation(store, sanitized, source="delegates_sanitized")

    if DEFAULT_DELEGATES_JSON_PATH.exists():
        payload = json.loads(DEFAULT_DELEGATES_JSON_PATH.read_text(encoding="utf-8"))
        for row in payload.get("delegates", []):
            for field in ("organisation", "affiliation"):
                value = str(row.get(field) or "").strip()
                if value:
                    _add_affiliation(store, value, source="delegates_raw")

    for path, source in (
        (PROJECT_ROOT / "js" / "locations.js", "map_locations"),
        (PROJECT_ROOT / "js" / "emissions-data.js", "emissions"),
        (PROJECT_ROOT / "js" / "speaker-profiles.js", "speaker_profiles"),
    ):
        for affiliation in _affiliations_from_js(path, source):
            _add_affiliation(store, affiliation, source=source)

    cache_path = DEFAULT_CACHE_PATH
    if cache_path.exists():
        cache = json.loads(cache_path.read_text(encoding="utf-8"))
        for key in cache:
            _add_affiliation(store, key, source="geocode_cache")

    if DEFAULT_OVERRIDES_PATH.exists():
        overrides = json.loads(DEFAULT_OVERRIDES_PATH.read_text(encoding="utf-8"))
        for key in overrides:
            _add_affiliation(store, key, source="geocode_overrides")

    profiles_path = PROJECT_ROOT / "data" / "speaker_profiles_cache.json"
    if profiles_path.exists():
        profiles = json.loads(profiles_path.read_text(encoding="utf-8"))
        for profile in profiles.values():
            affiliation = str(profile.get("affiliation") or "").strip()
            if affiliation:
                _add_affiliation(store, affiliation, source="speaker_profiles_cache")

    return store


def _country_suffix_only_cluster(variants: list[str]) -> bool:
    bases = {affiliation_base_name(variant) or variant for variant in variants}
    return len(bases) == 1


def _cluster_priority(
    cluster_variants: list[str],
    *,
    canonical_keys_differ: bool,
    country_suffix_only: bool,
) -> str:
    if looks_like_junk_affiliation(cluster_variants[0]):
        return "low"
    if canonical_keys_differ:
        return "high"
    if country_suffix_only:
        return "low"
    if len(cluster_variants) >= 3:
        return "high"
    return "medium"


def build_review_frames(
    records: dict[str, AffiliationRecord],
    *,
    fuzzy_threshold: float,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    clusters = cluster_affiliations(records, fuzzy_threshold=fuzzy_threshold)

    detail_rows: list[dict[str, object]] = []
    summary_rows: list[dict[str, object]] = []
    for cluster in clusters:
        variants = " | ".join(cluster.variants)
        canonical_keys = {canonical_affiliation_key(variant) for variant in cluster.variants}
        canonical_keys_differ = len(canonical_keys) > 1
        country_suffix_only = _country_suffix_only_cluster(cluster.variants)
        priority = _cluster_priority(
            cluster.variants,
            canonical_keys_differ=canonical_keys_differ,
            country_suffix_only=country_suffix_only,
        )
        summary_rows.append(
            {
                "cluster_id": cluster.cluster_id,
                "variant_count": len(cluster.variants),
                "total_occurrences": cluster.total_count,
                "priority": priority,
                "suggested_canonical": cluster.suggested_canonical,
                "match_reason": cluster.match_reason,
                "canonical_keys_differ": canonical_keys_differ,
                "country_suffix_only": country_suffix_only,
                "variants": variants,
                "needs_review": True,
                "confirmed_same": "",
                "approved_canonical": "",
            }
        )
        for record in cluster.records:
            detail_rows.append(
                {
                    "cluster_id": cluster.cluster_id,
                    "affiliation_variant": record.affiliation,
                    "occurrence_count": record.count,
                    "sources": "; ".join(sorted(record.sources)),
                    "canonical_key": canonical_affiliation_key(record.affiliation),
                    "display_name": affiliation_display_name(record.affiliation) or record.affiliation,
                    "fingerprint_key": affiliation_fingerprint_key(record.affiliation),
                    "token_key": affiliation_token_key(record.affiliation),
                    "suggested_canonical": cluster.suggested_canonical,
                    "match_reason": cluster.match_reason,
                    "priority": priority,
                    "cluster_variant_count": len(cluster.variants),
                    "cluster_total_occurrences": cluster.total_count,
                    "canonical_keys_differ": canonical_keys_differ,
                    "country_suffix_only": country_suffix_only,
                    "needs_review": True,
                    "confirmed_same": "",
                    "approved_canonical": "",
                }
            )

    detail = pd.DataFrame(detail_rows)
    if not detail.empty:
        detail = detail.sort_values(
            ["cluster_total_occurrences", "cluster_id", "occurrence_count"],
            ascending=[False, True, False],
        )
    summary = pd.DataFrame(summary_rows)
    if not summary.empty:
        priority_order = {"high": 0, "medium": 1, "low": 2}
        summary["priority_rank"] = summary["priority"].map(priority_order)
        summary = summary.sort_values(
            ["priority_rank", "total_occurrences", "variant_count"],
            ascending=[True, False, False],
        ).drop(columns=["priority_rank"])
    return detail, summary


def export_review_csv(
    output_path: Path = DEFAULT_OUTPUT_PATH,
    summary_path: Path = DEFAULT_SUMMARY_PATH,
    *,
    fuzzy_threshold: float = 0.93,
) -> tuple[Path, Path, int, int]:
    records = collect_affiliation_records()
    detail, summary = build_review_frames(records, fuzzy_threshold=fuzzy_threshold)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    detail.to_csv(output_path, index=False)
    summary.to_csv(summary_path, index=False)
    return output_path, summary_path, len(records), len(summary)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT_PATH,
        help="Detailed review CSV (one row per affiliation variant)",
    )
    parser.add_argument(
        "--summary",
        type=Path,
        default=DEFAULT_SUMMARY_PATH,
        help="Cluster summary CSV (one row per suspected duplicate group)",
    )
    parser.add_argument(
        "--fuzzy-threshold",
        type=float,
        default=0.93,
        help="Minimum fuzzy similarity to group affiliation variants (default: 0.93)",
    )
    args = parser.parse_args()

    output_path, summary_path, affiliation_count, cluster_count = export_review_csv(
        args.output,
        args.summary,
        fuzzy_threshold=args.fuzzy_threshold,
    )
    print(f"Scanned {affiliation_count:,} unique affiliation strings")
    print(f"Wrote {cluster_count:,} suspected duplicate clusters")
    print(f"Detail review: {output_path}")
    print(f"Cluster summary: {summary_path}")
    print(
        "Review the CSVs, set confirmed_same=TRUE/FALSE and approved_canonical where needed, "
        "then we can apply the approved names across the site."
    )


if __name__ == "__main__":
    main()
