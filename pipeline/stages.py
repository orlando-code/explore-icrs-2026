"""Pipeline stage implementations with verification metrics."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import pandas as pd

from pipeline.config import OVERRIDE_PRECEDENCE, PipelineConfig
from pipeline.report import StageReport
from pipeline.verify import (
    build_attendee_artifact,
    build_emissions_coverage_artifact,
    verify_emissions_coverage,
    verify_registry_coverage,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.geocoding.affiliation_geocodes import load_geocode_overrides, load_geocode_source_frames
from src.sources.delegates import load_delegates
from src.sources.programme import load_talks


def _pct(numerator: int, denominator: int) -> float:
    if denominator <= 0:
        return 0.0
    return round(100.0 * numerator / denominator, 2)


def _missing_org_country(delegates: pd.DataFrame) -> tuple[int, int]:
    missing_org = int(
        delegates["organisation"].isna().sum()
        + (delegates["organisation"].astype(str).str.strip() == "").sum()
    )
    missing_country = int(
        delegates["country"].isna().sum()
        + (delegates["country"].astype(str).str.strip() == "").sum()
    )
    return missing_org, missing_country


def run_delegates(
    config: PipelineConfig,
    *,
    refresh: bool = False,
) -> StageReport:
    """Stage 1: PDF → delegates.json (or load existing JSON)."""
    report = StageReport(stage="delegates", ok=True)

    pdf_exists = config.delegate_pdf.exists()
    json_exists = config.delegates_json.exists()
    report.metrics["pdf_present"] = pdf_exists
    report.metrics["json_present"] = json_exists

    if refresh and not pdf_exists:
        report.add_error(f"Cannot refresh: PDF not found at {config.delegate_pdf}")
        return report

    delegates = load_delegates(
        pdf_path=config.delegate_pdf,
        json_path=config.delegates_json,
        refresh=refresh,
    )

    speakers = int(delegates["is_speaker"].sum())
    non_speakers = int(len(delegates) - speakers)
    missing_org, missing_country = _missing_org_country(delegates)

    report.metrics.update(
        {
            "delegates": len(delegates),
            "speakers": speakers,
            "non_speakers": non_speakers,
            "missing_organisation": missing_org,
            "missing_country": missing_country,
            "org_override_rows": _count_csv_rows(config.org_overrides_csv),
            "refreshed_from_pdf": refresh,
        }
    )

    if missing_org:
        report.add_warning(f"{missing_org} delegates missing organisation")
    if missing_country:
        report.add_warning(f"{missing_country} delegates missing country")

    # Snapshot for downstream stages
    artifact = config.artifact("delegates.csv")
    artifact.parent.mkdir(parents=True, exist_ok=True)
    delegates.to_csv(artifact, index=False)
    report.metrics["artifact"] = str(artifact.relative_to(config.root))

    return report


def run_programme(config: PipelineConfig) -> StageReport:
    """Stage 2: Load programme snapshot and summarise talks."""
    report = StageReport(stage="programme", ok=True)

    if not config.programme_json.exists():
        report.add_error(f"Programme not found: {config.programme_json}")
        return report

    talks = load_talks(config.programme_json, config.abstracts_json)
    presenters = (
        talks["presenter"].dropna().astype(str).str.strip().replace("", pd.NA).dropna().nunique()
    )
    with_abstract = int(talks["has_abstract"].fillna(False).sum()) if "has_abstract" in talks.columns else 0
    with_affiliation = int(
        talks["affiliation"].dropna().astype(str).str.strip().replace("", pd.NA).dropna().shape[0]
    )

    report.metrics.update(
        {
            "talks": len(talks),
            "presenters": presenters,
            "with_abstract": with_abstract,
            "with_affiliation": with_affiliation,
            "abstract_coverage_pct": _pct(with_abstract, len(talks)),
            "affiliation_coverage_pct": _pct(with_affiliation, len(talks)),
        }
    )

    artifact = config.artifact("talks.csv")
    talks.to_csv(artifact, index=False)
    report.metrics["artifact"] = str(artifact.relative_to(config.root))

    return report


def run_registry(config: PipelineConfig) -> StageReport:
    """Stage 3: Build person registry with internal icrs-p-* keys."""
    from src.registry.person_registry import build_person_registry, save_person_registry

    report = StageReport(stage="registry", ok=True)
    result = build_person_registry()
    outputs = save_person_registry(
        result,
        registry_path=config.person_registry_csv,
        aliases_path=config.person_registry_csv.parent / "person_name_aliases.csv",
        unmatched_path=config.person_registry_csv.parent / "person_registry_unmatched.csv",
    )

    report.metrics.update(result.metrics)
    report.metrics["registry_path"] = str(outputs["registry"].relative_to(config.root))
    report.metrics["aliases_path"] = str(outputs["aliases"].relative_to(config.root))
    report.metrics["unmatched_path"] = str(outputs["unmatched"].relative_to(config.root))

    if result.metrics.get("programme_only_not_attended", 0):
        report.add_warning(
            f"{result.metrics['programme_only_not_attended']} programme presenters excluded from attendance (not on delegate list)"
        )
    if result.metrics.get("needs_review", 0):
        report.add_warning(
            f"{result.metrics['needs_review']} people flagged in person_registry_unmatched.csv"
        )

    artifact = config.artifact("person_registry.csv")
    result.registry.to_csv(artifact, index=False)
    report.metrics["artifact"] = str(artifact.relative_to(config.root))

    return report


def run_affiliations(config: PipelineConfig) -> StageReport:
    """Stage 4: Build affiliation registry with internal icrs-a-* keys."""
    from src.registry.affiliation_registry import build_affiliation_registry, save_affiliation_registry

    report = StageReport(stage="affiliations", ok=True)
    result = build_affiliation_registry()
    outputs = save_affiliation_registry(
        result,
        registry_path=config.affiliation_registry_csv,
        aliases_path=config.affiliation_registry_csv.parent / "affiliation_aliases.csv",
        unmatched_path=config.affiliation_registry_csv.parent / "affiliation_registry_unmatched.csv",
    )

    report.metrics.update(result.metrics)
    for label, path in outputs.items():
        report.metrics[f"{label}_path"] = str(path.relative_to(config.root))

    if result.metrics.get("geocode_missing_or_failed", 0):
        report.add_warning(
            f"{result.metrics['geocode_missing_or_failed']} affiliations missing geocodes"
        )

    artifact = config.artifact("affiliation_registry.csv")
    result.registry.to_csv(artifact, index=False)
    report.metrics["artifact"] = str(artifact.relative_to(config.root))

    from src.geocoding.foreign_delegate import (
        build_foreign_delegate_standardisation,
        export_foreign_delegate_standardisation,
    )

    foreign_path = export_foreign_delegate_standardisation()
    foreign_frame = build_foreign_delegate_standardisation(attended_only=True)
    report.metrics["foreign_delegate_anchors"] = str(foreign_path.relative_to(config.root))
    report.metrics["foreign_delegate_anchor_count"] = len(foreign_frame)
    return report


def run_geocode(
    config: PipelineConfig,
    *,
    refresh: bool = False,
) -> StageReport:
    """Stage 5: Verify geocode coverage via affiliation registry (optionally refresh CSV)."""
    report = StageReport(stage="geocode", ok=True)

    if refresh:
        from src.geocoding.geocode_refresh import refresh_geocodes

        refresh_geocodes(output_csv=config.affiliation_geocodes_csv)
        from src.registry.affiliation_registry import build_affiliation_registry, save_affiliation_registry

        result = build_affiliation_registry()
        save_affiliation_registry(result, registry_path=config.affiliation_registry_csv)

    registry_path = config.affiliation_registry_csv
    person_registry_path = config.person_registry_csv
    if not registry_path.exists():
        report.add_error(
            f"Affiliation registry missing: {registry_path}. Run: build_pipeline.py affiliations"
        )
        return report
    if not person_registry_path.exists():
        report.add_error(
            f"Person registry missing: {person_registry_path}. Run: build_pipeline.py registry"
        )
        return report

    geocodes = load_geocode_source_frames(
        config.affiliation_geocodes_csv,
        manual_path=config.manual_geocodes_csv,
    )
    ok_rows = int(geocodes["status"].eq("OK").sum()) if not geocodes.empty and "status" in geocodes.columns else 0
    failed_rows = len(geocodes) - ok_rows if not geocodes.empty else 0
    overrides = load_geocode_overrides(config.geocode_overrides_json)

    coverage = verify_registry_coverage()
    report.metrics.update(coverage)
    report.metrics.update(
        {
            "geocode_rows_total": len(geocodes),
            "geocode_rows_ok": ok_rows,
            "geocode_rows_failed": failed_rows,
            "geocode_ok_pct": _pct(ok_rows, len(geocodes)),
            "coordinate_overrides": len(overrides),
            "manual_geocode_rows": _count_csv_rows(config.manual_geocodes_csv),
            "override_precedence": list(OVERRIDE_PRECEDENCE),
        }
    )

    if failed_rows:
        report.add_warning(f"{failed_rows} affiliation geocode rows failed (see CSV status column)")
    if coverage.get("attended_geocode_pct", 0) < 95:
        report.add_warning("Attended-person geocode coverage below 95%")
    if coverage.get("affiliations_needs_review", 0):
        report.add_warning(
            f"{coverage['affiliations_needs_review']} affiliations still flagged needs_review"
        )

    artifact = config.artifact("geocoded_attendees.csv")
    build_attendee_artifact().to_csv(artifact, index=False)
    report.metrics["artifact"] = str(artifact.relative_to(config.root))

    return report


def run_export_site(config: PipelineConfig, *, quiet: bool = False) -> StageReport:
    """Stage 5: Export map site JS modules via existing export script."""
    report = StageReport(stage="export-site", ok=True)
    script = config.root / "scripts" / "pipeline" / "export_attendee_site.py"
    args = [sys.executable, str(script), "--output", str(config.locations_js)]
    if quiet:
        args.append("--quiet")

    subprocess.run(args, check=True, cwd=config.root)

    for path in (config.locations_js, config.talks_js):
        if not path.exists():
            report.add_error(f"Expected output missing: {path}")
            continue
        report.metrics[f"{path.stem}_bytes"] = path.stat().st_size

    delegates_js = config.root / "js" / "non-speaking-delegates.js"
    if delegates_js.exists():
        report.metrics["non_speaking_delegates_bytes"] = delegates_js.stat().st_size

    # Parse stats from locations.js if present
    if config.locations_js.exists():
        text = config.locations_js.read_text(encoding="utf-8")
        if '"stats"' in text:
            try:
                stats_start = text.index('"stats":')
                snippet = text[stats_start : stats_start + 800]
                # crude extract of location_count if exported
                for key in ("location_count", "speaker_count", "connection_count"):
                    marker = f'"{key}":'
                    if marker in snippet:
                        val = snippet.split(marker, 1)[1].split(",", 1)[0].strip()
                        report.metrics[key] = int(val)
            except (ValueError, IndexError):
                pass

    return report


def run_emissions(
    config: PipelineConfig,
    *,
    fetch_missing: bool = True,
    requery_all: bool = False,
    quiet: bool = False,
) -> StageReport:
    """Stage 6: Build emissions-data.js from geocoded legs and travel route cache."""
    from src.emissions.emissions_build import build_emissions_site

    report = StageReport(stage="emissions", ok=True)

    try:
        result = build_emissions_site(
            emissions_path=config.emissions_js,
            artifacts_dir=config.artifact("emissions_travel_legs.csv").parent,
            fetch_missing_routes=fetch_missing,
            requery_all_routes=requery_all,
            show_progress=not quiet,
        )
    except Exception as exc:
        report.add_error(str(exc))
        return report

    report.metrics["emissions_js_bytes"] = config.emissions_js.stat().st_size
    report.metrics["routes_queried"] = result.routes_queried
    report.metrics["routes_missing_before"] = result.routes_missing_before
    report.metrics["delegate_estimates"] = len(result.delegate_estimates)

    legs_artifact = config.artifact("emissions_travel_legs.csv")
    estimates_artifact = config.artifact("emissions_delegate_estimates.csv")
    coverage = verify_emissions_coverage(
        emissions_js=config.emissions_js,
        legs_path=legs_artifact,
        estimates_path=estimates_artifact,
    )
    report.metrics.update(coverage)

    coverage_artifact = config.artifact("emissions_coverage.csv")
    build_emissions_coverage_artifact(
        emissions_js=config.emissions_js,
        legs_path=legs_artifact,
        estimates_path=estimates_artifact,
    ).to_csv(coverage_artifact, index=False)
    report.metrics["artifact"] = str(coverage_artifact.relative_to(config.root))

    if coverage.get("missing_co2e_count", 0):
        report.add_warning(
            f"{coverage['missing_co2e_count']} attended people without CO2e in export "
            f"(see {coverage_artifact.name})"
        )
    if coverage.get("registry_geocode_pct", 0) < 99:
        report.add_warning("Registry geocode coverage below 99% for attended people")

    return report


def _count_csv_rows(path: Path) -> int:
    if not path.exists():
        return 0
    df = pd.read_csv(path, encoding="utf-8", encoding_errors="replace")
    return len(df)


STAGE_RUNNERS = {
    "delegates": run_delegates,
    "programme": run_programme,
    "registry": run_registry,
    "affiliations": run_affiliations,
    "geocode": run_geocode,
    "export-site": run_export_site,
    "emissions": run_emissions,
}
