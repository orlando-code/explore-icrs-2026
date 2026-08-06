"""Verification reports for pipeline stages."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from rich.console import Console
from rich.table import Table

_CONSOLE = Console(stderr=True)


@dataclass
class StageReport:
    stage: str
    ok: bool
    metrics: dict[str, Any] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    generated_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(timespec="seconds")
    )

    def add_warning(self, message: str) -> None:
        self.warnings.append(message)

    def add_error(self, message: str) -> None:
        self.errors.append(message)
        self.ok = False

    def save(self, path: Path) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(asdict(self), indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        return path

    @classmethod
    def load(cls, path: Path) -> StageReport:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return cls(**payload)


def print_report(report: StageReport) -> None:
    status = "[bold green]OK[/]" if report.ok else "[bold red]FAILED[/]"
    _CONSOLE.print(f"\n[bold]{report.stage}[/] {status}")

    if report.metrics:
        table = Table(show_header=True, header_style="bold", box=None, padding=(0, 2))
        table.add_column("Metric")
        table.add_column("Value", justify="right")
        for key, value in report.metrics.items():
            if isinstance(value, float):
                display = f"{value:,.2f}"
            elif isinstance(value, int):
                display = f"{value:,}"
            else:
                display = str(value)
            table.add_row(key, display)
        _CONSOLE.print(table)

    for warning in report.warnings:
        _CONSOLE.print(f"  [yellow]![/] {warning}")
    for error in report.errors:
        _CONSOLE.print(f"  [red]✗[/] {error}")


def load_all_reports(reports_dir: Path) -> list[StageReport]:
    if not reports_dir.exists():
        return []
    reports: list[StageReport] = []
    for path in sorted(reports_dir.glob("*.json")):
        reports.append(StageReport.load(path))
    return reports


def print_summary(reports: list[StageReport]) -> None:
    if not reports:
        _CONSOLE.print("[dim]No pipeline reports found.[/]")
        return

    table = Table(title="Pipeline verification summary", show_header=True, header_style="bold")
    table.add_column("Stage")
    table.add_column("Status")
    table.add_column("Key metrics")

    for report in reports:
        status = "[green]ok[/]" if report.ok else "[red]fail[/]"
        highlights: list[str] = []
        for key in ("delegates", "talks", "presenters", "speaker_geocode_pct", "delegate_geocode_pct"):
            if key in report.metrics:
                val = report.metrics[key]
                if isinstance(val, float):
                    highlights.append(f"{key}={val:.1f}%")
                else:
                    highlights.append(f"{key}={val}")
        table.add_row(report.stage, status, ", ".join(highlights) or "—")

    _CONSOLE.print()
    _CONSOLE.print(table)
