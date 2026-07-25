"""Precompute talk similarity maps with local Ollama embeddings."""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np

OLLAMA_URL = "http://localhost:11434"
DEFAULT_EMBED_MODEL = "nomic-embed-text"
DEFAULT_TOP_K = 5
DEFAULT_WORKERS = 8


def tokenize(text: str) -> set[str]:
    return {
        word
        for word in re.sub(r"[^a-z0-9\s]", " ", str(text or "").lower()).split()
        if len(word) > 2
    }


def shared_keyword_reason(source: dict[str, Any], candidate: dict[str, Any], limit: int = 4) -> str:
    shared = sorted(
        tokenize(f"{source.get('title', '')} {source.get('abstract', '')}")
        & tokenize(f"{candidate.get('title', '')} {candidate.get('abstract', '')}"),
        key=lambda word: (-len(word), word),
    )[:limit]
    return ", ".join(shared) if shared else "Related topic"


def talk_embed_text(talk: dict[str, Any], *, max_chars: int = 6000) -> str:
    abstract = str(talk.get("abstract") or "")
    if len(abstract) > max_chars:
        abstract = f"{abstract[: max_chars - 1]}…"
    return f"{talk.get('title', '')}\n\n{abstract}".strip()


def _ollama_embed(text: str, *, model: str, timeout: float = 120.0) -> np.ndarray:
    payload = json.dumps({"model": model, "prompt": text}).encode("utf-8")
    request = urllib.request.Request(
        f"{OLLAMA_URL}/api/embeddings",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            data = json.loads(response.read().decode("utf-8"))
    except urllib.error.URLError as exc:
        raise RuntimeError(
            f"Could not reach Ollama at {OLLAMA_URL}. Is it running?"
        ) from exc

    embedding = data.get("embedding")
    if not embedding:
        raise RuntimeError(data.get("error", "Ollama returned no embedding."))
    return np.asarray(embedding, dtype=np.float32)


def _load_embedding_cache(cache_path: Path, model: str) -> tuple[list[str], np.ndarray | None]:
    meta_path = cache_path.with_suffix(".meta.json")
    if not cache_path.exists() or not meta_path.exists():
        return [], None

    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    if meta.get("model") != model:
        return [], None

    cached = np.load(cache_path)
    return [str(item) for item in cached["ids"].tolist()], cached["embeddings"]


def _save_embedding_cache(
    cache_path: Path,
    *,
    model: str,
    ids: list[str],
    embeddings: np.ndarray,
) -> None:
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(cache_path, ids=np.asarray(ids, dtype=object), embeddings=embeddings)
    meta = {
        "model": model,
        "count": len(ids),
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
    }
    cache_path.with_suffix(".meta.json").write_text(
        json.dumps(meta, indent=2),
        encoding="utf-8",
    )


def build_talk_embeddings(
    talks_by_id: dict[str, dict[str, Any]],
    *,
    model: str = DEFAULT_EMBED_MODEL,
    cache_path: str | Path = "data/talk_embeddings.npz",
    workers: int = DEFAULT_WORKERS,
    show_progress: bool = True,
) -> tuple[list[str], np.ndarray]:
    talks = [talks_by_id[talk_id] for talk_id in sorted(talks_by_id)]
    talk_ids = [talk["id"] for talk in talks]
    cache_file = Path(cache_path)

    cached_ids, cached_embeddings = _load_embedding_cache(cache_file, model)
    cached_map: dict[str, np.ndarray] = {}
    if cached_ids and cached_embeddings is not None:
        cached_map = {
            talk_id: cached_embeddings[index] for index, talk_id in enumerate(cached_ids)
        }

    missing_talks = [talk for talk in talks if talk["id"] not in cached_map]
    if missing_talks:
        if show_progress:
            print(f"Embedding {len(missing_talks)} talks with {model} ({workers} workers)…")

        def embed_talk(talk: dict[str, Any]) -> tuple[str, np.ndarray]:
            vector = _ollama_embed(talk_embed_text(talk), model=model)
            return talk["id"], vector

        with ThreadPoolExecutor(max_workers=max(workers, 1)) as executor:
            futures = {executor.submit(embed_talk, talk): talk["id"] for talk in missing_talks}
            completed = 0
            for future in as_completed(futures):
                talk_id, vector = future.result()
                cached_map[talk_id] = vector
                completed += 1
                if show_progress and (
                    completed == len(missing_talks) or completed % 100 == 0
                ):
                    print(f"  embedded {completed}/{len(missing_talks)}")

    ordered_ids = talk_ids
    embeddings = np.vstack([cached_map[talk_id] for talk_id in ordered_ids]).astype(np.float32)
    _save_embedding_cache(cache_file, model=model, ids=ordered_ids, embeddings=embeddings)
    return ordered_ids, embeddings


def build_talk_similarity_map(
    talks_by_id: dict[str, dict[str, Any]],
    *,
    model: str = DEFAULT_EMBED_MODEL,
    top_k: int = DEFAULT_TOP_K,
    cache_path: str | Path = "data/talk_embeddings.npz",
    workers: int = DEFAULT_WORKERS,
    show_progress: bool = True,
) -> dict[str, list[dict[str, Any]]]:
    talk_ids, embeddings = build_talk_embeddings(
        talks_by_id,
        model=model,
        cache_path=cache_path,
        workers=workers,
        show_progress=show_progress,
    )

    if show_progress:
        print(f"Computing top-{top_k} similarities for {len(talk_ids)} talks…")

    norms = np.linalg.norm(embeddings, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    normalized = embeddings / norms
    similarity = normalized @ normalized.T

    by_id: dict[str, list[dict[str, Any]]] = {}
    for index, talk_id in enumerate(talk_ids):
        scores = similarity[index].copy()
        scores[index] = -1.0
        if top_k >= len(scores):
            candidate_idx = np.argsort(scores)[::-1]
        else:
            candidate_idx = np.argpartition(scores, -top_k)[-top_k:]
            candidate_idx = candidate_idx[np.argsort(scores[candidate_idx])[::-1]]

        entries: list[dict[str, Any]] = []
        source = talks_by_id[talk_id]
        for candidate_index in candidate_idx:
            score = float(scores[candidate_index])
            if score <= 0:
                continue
            candidate_id = talk_ids[candidate_index]
            entries.append(
                {
                    "id": candidate_id,
                    "score": round(score, 4),
                    "reason": shared_keyword_reason(source, talks_by_id[candidate_id]),
                }
            )
            if len(entries) >= top_k:
                break
        by_id[talk_id] = entries

    return by_id


def export_talk_similarities_js(
    similarities_by_id: dict[str, list[dict[str, Any]]],
    *,
    model: str,
    save_path: str | Path = "js/talk-similarities.js",
) -> Path:
    payload = {
        "meta": {
            "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
            "method": "ollama-embeddings",
            "model": model,
            "top_k": DEFAULT_TOP_K,
            "talk_count": len(similarities_by_id),
        },
        "by_id": similarities_by_id,
    }
    output_path = Path(save_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        "/** Generated by build_talk_similarities.py – do not edit by hand. */\n"
        f"export const TALK_SIMILARITIES = {json.dumps(payload, ensure_ascii=True, separators=(',', ':'))};\n",
        encoding="utf-8",
    )
    return output_path
