"""Shared JSON read/write helpers for the pipeline."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

_MISSING = object()


def load_json(path: Path | str, *, default: Any = _MISSING) -> Any:
    """Load UTF-8 JSON from ``path``.

    If the file is missing and ``default`` is provided, return ``default``.
    Otherwise raise ``FileNotFoundError``.
    """
    path = Path(path)
    if not path.exists():
        if default is _MISSING:
            raise FileNotFoundError(f"JSON not found: {path}")
        return default
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def save_json(
    path: Path | str,
    payload: Any,
    *,
    indent: int | None = 2,
    sort_keys: bool = True,
    ensure_ascii: bool = False,
) -> Path:
    """Write ``payload`` as UTF-8 JSON, creating parent directories as needed."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(
            payload,
            handle,
            indent=indent,
            sort_keys=sort_keys,
            ensure_ascii=ensure_ascii,
        )
    return path
