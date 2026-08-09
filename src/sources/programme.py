"""Load ICRS programme and talk data into a regular tabular format."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd

from src.data_paths import ABSTRACTS_JSON, PROGRAMME_JSON

TALK_COLUMNS = [
    "talk_id",
    "sid",
    "title",
    "presenter",
    "primary_author",
    "authors",
    "affiliation",
    "honorific",
    "position",
    "has_abstract",
    "abstract",
    "theme_cat",
    "start",
    "end",
    "date",
    "session_id",
    "session_title",
    "session_kind",
    "presentation_type",
    "session_code",
    "session_theme",
    "room",
    "location",
]


def classify_presentation_type(session_kind: object) -> str:
    """Map programme session kind to poster, oral, or keynote."""
    kind = str(session_kind or "").strip().casefold()
    if kind == "poster":
        return "poster"
    if kind == "plenary":
        return "keynote"
    if kind in {"session", "special"}:
        return "oral"
    return ""


def _load_json(path: Path) -> Any:
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def load_talks(
    programme_path: str | Path = PROGRAMME_JSON,
    abstracts_path: str | Path | None = ABSTRACTS_JSON,
) -> pd.DataFrame:
    """Flatten session talks into one row per talk.

    The presenting author is treated as the primary author. Their affiliation
    is taken from the talk's ``affiliation`` field.
    """
    programme_path = Path(programme_path)
    programme = _load_json(programme_path)

    abstracts: dict[str, str] = {}
    if abstracts_path is not None:
        abstracts_path = Path(abstracts_path)
        if abstracts_path.exists():
            abstracts = _load_json(abstracts_path)

    rows: list[dict[str, Any]] = []
    for session in programme["sessions"]:
        for talk in session["talks"]:
            authors = talk.get("authors") or []
            presenter = talk.get("presenter") or (authors[0] if authors else None)
            sid = talk.get("sid")

            rows.append(
                {
                    "talk_id": talk.get("id"),
                    "sid": sid,
                    "title": talk.get("title"),
                    "presenter": presenter,
                    "primary_author": presenter,
                    "authors": authors,
                    "affiliation": (talk.get("affiliation") or "").strip(),
                    "honorific": talk.get("honorific") or pd.NA,
                    "position": talk.get("position") or pd.NA,
                    "has_abstract": bool(talk.get("hasAbstract")),
                    "abstract": abstracts.get(sid) if sid else pd.NA,
                    "theme_cat": talk.get("themeCat"),
                    "start": talk.get("start"),
                    "end": talk.get("end"),
                    "date": session.get("date"),
                    "session_id": session.get("id"),
                    "session_title": session.get("title"),
                    "session_kind": session.get("kind"),
                    "presentation_type": classify_presentation_type(session.get("kind")),
                    "session_code": session.get("code"),
                    "session_theme": session.get("theme"),
                    "room": session.get("room"),
                    "location": session.get("location"),
                }
            )

    return pd.DataFrame(rows, columns=TALK_COLUMNS)
