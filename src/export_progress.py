"""Progress reporting for long-running data exports."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from typing import TypeVar

import pandas as pd
from rich.console import Console
from rich.progress import (
    BarColumn,
    Progress,
    SpinnerColumn,
    TaskProgressColumn,
    TextColumn,
    TimeElapsedColumn,
)

T = TypeVar("T")
_CONSOLE = Console(stderr=True)


def console() -> Console:
    return _CONSOLE


def make_progress(*, disable: bool = False) -> Progress:
    return Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TaskProgressColumn(),
        TimeElapsedColumn(),
        console=_CONSOLE,
        disable=disable,
    )


@contextmanager
def export_stage(label: str):
    _CONSOLE.print(f"[bold cyan]→[/] {label}")
    try:
        yield
    except Exception:
        _CONSOLE.print(f"[bold red]✗[/] {label}")
        raise
    else:
        _CONSOLE.print(f"[bold green]✓[/] {label}")


def iterrows_with_progress(
    frame: pd.DataFrame,
    description: str,
    *,
    show_progress: bool = True,
) -> Iterator[tuple[object, pd.Series]]:
    if not show_progress or frame.empty:
        yield from frame.iterrows()
        return

    with make_progress() as progress:
        task_id = progress.add_task(description, total=len(frame))
        for index, row in frame.iterrows():
            yield index, row
            progress.advance(task_id)


def run_with_progress(
    description: str,
    func: Callable[[], T],
    *,
    show_progress: bool = True,
) -> T:
    if not show_progress:
        return func()

    with make_progress() as progress:
        task_id = progress.add_task(description, total=1)
        result = func()
        progress.advance(task_id)
        return result
