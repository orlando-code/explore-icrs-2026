"""ISO-3166 alpha-2 continent lookup for privacy clustering."""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
CONTINENTS_PATH = PROJECT_ROOT / "data" / "country_continents.json"


@lru_cache(maxsize=1)
def load_country_continents() -> dict[str, str]:
    if not CONTINENTS_PATH.exists():
        return {}
    payload = json.loads(CONTINENTS_PATH.read_text(encoding="utf-8"))
    return {
        str(code).strip().upper(): str(continent).strip()
        for code, continent in payload.items()
        if str(code).strip() and str(continent).strip()
    }


def continent_for_country(code: str, continents: dict[str, str] | None = None) -> str:
    mapping = continents or load_country_continents()
    return mapping.get(str(code or "").strip().upper(), "")


def same_continent(
    left: str,
    right: str,
    continents: dict[str, str] | None = None,
) -> bool:
    left_continent = continent_for_country(left, continents)
    right_continent = continent_for_country(right, continents)
    if not left_continent or not right_continent:
        return False
    return left_continent == right_continent
