#!/usr/bin/env python3
"""Export public profile/contact hints for ICRS network speakers."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from rich.console import Console
from rich.table import Table

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.plot_utils import _author_affiliation_map, author_talk_counts
from src.programme import load_talks
from src.speaker_profiles import (
    DEFAULT_BRAVE_BUDGET,
    DEFAULT_CACHE_PATH,
    DEFAULT_WORKERS,
    ProfileBuildStats,
    _profile_key,
    build_speaker_profiles,
    export_speaker_profiles_js,
    load_profile_cache,
    print_profile_build_summary,
    summarize_profiles,
)

console = Console()


def _profiles_from_cache(
    speakers: list[tuple[str, str]],
    cache_path: str | Path,
) -> dict:
    cache = load_profile_cache(cache_path)
    return {
        name: cache[_profile_key(name, affiliation)]
        for name, affiliation in speakers
        if _profile_key(name, affiliation) in cache
    }


def _speakers_by_connections(
    author_map: dict[str, str],
    talk_counts: dict[str, int],
) -> list[tuple[str, str]]:
    return sorted(
        author_map.items(),
        key=lambda item: (-talk_counts.get(item[0], 0), item[0].casefold()),
    )


def _print_smoke_test(
    speakers: list[tuple[str, str]],
    profiles: dict,
    talk_counts: dict[str, int],
    *,
    brave_requests: int,
) -> None:
    table = Table(title="Brave smoke test", show_header=True, header_style="bold")
    table.add_column("Rank", justify="right")
    table.add_column("Talks", justify="right")
    table.add_column("Speaker")
    table.add_column("Affiliation")
    table.add_column("Primary contact")
    table.add_column("Profile page")

    for index, (name, affiliation) in enumerate(speakers, start=1):
        profile = profiles.get(name, {})
        primary = profile.get("primary") or {}
        primary_text = primary.get("label") or primary.get("type") or "–"
        if primary.get("type") == "email":
            primary_text = primary.get("url", primary_text)
        page = profile.get("institutional_page") or profile.get("profile_page") or "–"
        if len(page) > 48:
            page = f"{page[:45]}..."
        table.add_row(
            str(index),
            str(talk_counts.get(name, 0)),
            name,
            affiliation[:40] + ("…" if len(affiliation) > 40 else ""),
            primary_text,
            page,
        )

    console.print(table)
    console.print(f"[dim]Brave API requests used this run: {brave_requests}[/]")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        default="js/speaker-profiles.js",
        help="Path for generated JS module.",
    )
    parser.add_argument(
        "--cache",
        default=str(DEFAULT_CACHE_PATH),
        help="JSON cache for profile lookups.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Limit number of speakers queried (for testing).",
    )
    parser.add_argument(
        "--retry-failed",
        action="store_true",
        help="Re-query speakers with low-confidence or search-only matches.",
    )
    parser.add_argument(
        "--export-only",
        action="store_true",
        help="Write js/speaker-profiles.js from cache without new lookups.",
    )
    parser.add_argument(
        "--names",
        nargs="*",
        default=None,
        help="Only look up these speaker names (space-separated).",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=DEFAULT_WORKERS,
        help=f"Parallel lookup workers (default: {DEFAULT_WORKERS}). Use 1 for sequential.",
    )
    parser.add_argument(
        "--brave-budget",
        type=int,
        default=DEFAULT_BRAVE_BUDGET,
        help=f"Max Brave Search API requests per run (default: {DEFAULT_BRAVE_BUDGET}).",
    )
    parser.add_argument(
        "--smoke-test",
        type=int,
        default=None,
        metavar="N",
        help="Look up top N speakers by talk count and print a summary table.",
    )
    args = parser.parse_args()

    talks = load_talks()
    author_map = _author_affiliation_map(talks)
    talk_counts = author_talk_counts(talks)
    speakers = _speakers_by_connections(author_map, talk_counts)

    if args.smoke_test is not None:
        args.limit = args.smoke_test
        args.workers = 1

    run_stats: ProfileBuildStats | None = None
    queried_speakers = speakers
    if args.limit is not None:
        queried_speakers = speakers[: args.limit]

    if not args.export_only:
        _, run_stats = build_speaker_profiles(
            speakers,
            cache_path=args.cache,
            show_progress=True,
            limit=args.limit,
            retry_failed=args.retry_failed,
            names=args.names,
            console=console,
            workers=args.workers,
            brave_budget=args.brave_budget,
        )

    all_profiles = _profiles_from_cache(speakers, args.cache)
    output = export_speaker_profiles_js(all_profiles, save_path=args.output)
    print_profile_build_summary(
        run_stats
        or ProfileBuildStats(total=len(all_profiles), cached=len(all_profiles)),
        cache_path=args.cache,
        output_path=output,
        profile_counts=summarize_profiles(all_profiles),
        console=console,
    )

    if args.smoke_test is not None:
        _print_smoke_test(
            queried_speakers,
            all_profiles,
            talk_counts,
            brave_requests=run_stats.brave_requests if run_stats else 0,
        )


if __name__ == "__main__":
    main()
