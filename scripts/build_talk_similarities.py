#!/usr/bin/env python3
"""Precompute talk similarity map with local Ollama embeddings."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.programme import load_talks
from src.talk_similarity_build import (
    DEFAULT_EMBED_MODEL,
    DEFAULT_TOP_K,
    build_talk_similarity_map,
    export_talk_similarities_js,
)
from src.talks_export import build_talk_catalog


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--model",
        default=DEFAULT_EMBED_MODEL,
        help=f"Ollama embedding model (default: {DEFAULT_EMBED_MODEL})",
    )
    parser.add_argument(
        "--top-k",
        type=int,
        default=DEFAULT_TOP_K,
        help=f"Similar talks per talk (default: {DEFAULT_TOP_K})",
    )
    parser.add_argument(
        "--output",
        default="js/talk-similarities.js",
        help="Path for generated JS module",
    )
    parser.add_argument(
        "--cache",
        default="data/talk_embeddings.npz",
        help="Embedding cache path",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=8,
        help="Parallel Ollama embedding workers",
    )
    args = parser.parse_args()

    talks = load_talks()
    catalog = build_talk_catalog(talks)
    similarities = build_talk_similarity_map(
        catalog["by_id"],
        model=args.model,
        top_k=args.top_k,
        cache_path=args.cache,
        workers=args.workers,
        show_progress=True,
    )
    output = export_talk_similarities_js(
        similarities,
        model=args.model,
        save_path=args.output,
    )
    print(f"Wrote {output} ({len(similarities)} talks, top {args.top_k})")


if __name__ == "__main__":
    main()
