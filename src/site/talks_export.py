"""Export talk metadata for the static site (no plotting dependencies)."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd


def build_talk_catalog(
    df: pd.DataFrame,
    *,
    title_col: str = "title",
    abstract_col: str = "abstract",
    presenter_col: str = "presenter",
    show_progress: bool = False,
) -> dict[str, Any]:
    from src.site.export_progress import make_progress

    by_id: dict[str, dict[str, Any]] = {}
    title_index: dict[str, list[str]] = {}

    columns = [
        column
        for column in (
            "talk_id",
            title_col,
            abstract_col,
            presenter_col,
            "authors",
            "session_title",
            "presentation_type",
            "date",
            "start",
            "person_key",
            "affiliation_key",
            "affiliation",
        )
        if column in df.columns
    ]
    working = df[columns]
    column_index = {name: index for index, name in enumerate(columns)}
    rows = list(working.itertuples(index=False, name=None))

    progress = make_progress(disable=not show_progress)
    with progress:
        task_id = progress.add_task("Building talks catalog", total=len(rows))
        for row in rows:
            talk_id = row[column_index["talk_id"]] if "talk_id" in column_index else None
            title = row[column_index[title_col]]
            if pd.isna(talk_id) or pd.isna(title) or not str(title).strip():
                progress.advance(task_id)
                continue
            talk_id_text = str(talk_id).strip()
            title_text = str(title).strip()
            abstract = (
                row[column_index[abstract_col]]
                if abstract_col in column_index
                else None
            )
            presenter = row[column_index[presenter_col]]
            authors = _talk_authors_from_values(
                row[column_index["authors"]] if "authors" in column_index else None,
                presenter,
            )
            talk = {
                "id": talk_id_text,
                "title": title_text,
                "authors": authors,
                "presenter": "" if pd.isna(presenter) else str(presenter).strip(),
                "abstract": "" if pd.isna(abstract) else str(abstract).strip(),
                "session_title": ""
                if "session_title" not in column_index
                or pd.isna(row[column_index["session_title"]])
                else str(row[column_index["session_title"]]).strip(),
                "presentation_type": ""
                if "presentation_type" not in column_index
                or pd.isna(row[column_index["presentation_type"]])
                else str(row[column_index["presentation_type"]]).strip(),
                "date": ""
                if "date" not in column_index or pd.isna(row[column_index["date"]])
                else str(row[column_index["date"]]).strip(),
                "start": ""
                if "start" not in column_index or pd.isna(row[column_index["start"]])
                else str(row[column_index["start"]]).strip(),
            }
            if "person_key" in column_index:
                talk["person_key"] = str(row[column_index["person_key"]] or "").strip()
            if "affiliation_key" in column_index:
                talk["affiliation_key"] = str(
                    row[column_index["affiliation_key"]] or ""
                ).strip()
            if "affiliation" in column_index:
                talk["affiliation"] = (
                    ""
                    if pd.isna(row[column_index["affiliation"]])
                    else str(row[column_index["affiliation"]]).strip()
                )
            by_id[talk_id_text] = talk
            title_index.setdefault(title_text.casefold(), []).append(talk_id_text)
            progress.advance(task_id)

    return {"by_id": by_id, "title_index": title_index}


def _talk_authors_from_values(
    authors: Any,
    presenter: Any,
) -> list[str]:
    if isinstance(authors, list) and authors:
        return [str(author).strip() for author in authors if str(author).strip()]
    if pd.isna(presenter) or not str(presenter).strip():
        return []
    return [str(presenter).strip()]


def export_talks_catalog(
    df: pd.DataFrame,
    *,
    save_path: str | Path = "js/talks.js",
    show_progress: bool = False,
) -> Path:
    """Export full talk metadata for the static site talk detail panel."""
    catalog = build_talk_catalog(df, show_progress=show_progress)
    payload = {
        "meta": {
            "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
            "talk_count": len(catalog["by_id"]),
        },
        "by_id": catalog["by_id"],
        "title_index": catalog["title_index"],
    }
    output_path = Path(save_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        "/** Generated by export_talks_catalog – do not edit by hand. */\n"
        f"export const TALKS_DATA = {json.dumps(payload, ensure_ascii=True, indent=2)};\n",
        encoding="utf-8",
    )
    return output_path
