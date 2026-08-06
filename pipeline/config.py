"""Paths and override precedence for the ICRS data pipeline."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from src.data_paths import (
    ABSTRACTS_JSON,
    AFFILIATION_DISPLAY_ALIASES_JSON,
    AFFILIATION_GEOCODES_CSV,
    AFFILIATION_GEOCODES_MANUAL_CSV,
    AFFILIATION_REGISTRY_CSV,
    DELEGATE_ORG_OVERRIDES_CSV,
    DELEGATE_PDF,
    DELEGATES_JSON,
    GEOCODE_OVERRIDES_JSON,
    MAP_EXCLUDED_NAMES_TXT,
    PERSON_REGISTRY_CSV,
    PROGRAMME_JSON,
    PROJECT_ROOT,
)

# Canonical stage order. Each stage writes a verification report under
# pipeline/reports/<stage>.json and may write artifacts under pipeline/artifacts/.
PIPELINE_STAGES = (
    "delegates",
    "programme",
    "registry",
    "affiliations",
    "geocode",
    "export-site",
    "emissions",
)


@dataclass(frozen=True)
class PipelineConfig:
    """Resolved paths for one pipeline run."""

    root: Path = PROJECT_ROOT
    artifacts_dir: Path = field(default_factory=lambda: PROJECT_ROOT / "pipeline" / "artifacts")
    reports_dir: Path = field(default_factory=lambda: PROJECT_ROOT / "pipeline" / "reports")

    # Raw / committed data
    programme_json: Path = PROGRAMME_JSON
    abstracts_json: Path = ABSTRACTS_JSON
    delegate_pdf: Path = DELEGATE_PDF
    delegates_json: Path = DELEGATES_JSON
    affiliation_geocodes_csv: Path = AFFILIATION_GEOCODES_CSV

    # Manual overrides (kept separate; applied in documented order)
    org_overrides_csv: Path = DELEGATE_ORG_OVERRIDES_CSV
    geocode_overrides_json: Path = GEOCODE_OVERRIDES_JSON
    display_aliases_json: Path = AFFILIATION_DISPLAY_ALIASES_JSON
    manual_geocodes_csv: Path = AFFILIATION_GEOCODES_MANUAL_CSV
    affiliation_registry_csv: Path = AFFILIATION_REGISTRY_CSV
    person_registry_csv: Path = PERSON_REGISTRY_CSV
    map_exclusions_txt: Path = MAP_EXCLUDED_NAMES_TXT

    # Generated site modules
    locations_js: Path = field(default_factory=lambda: PROJECT_ROOT / "js" / "locations.js")
    talks_js: Path = field(default_factory=lambda: PROJECT_ROOT / "js" / "talks.js")
    emissions_js: Path = field(default_factory=lambda: PROJECT_ROOT / "js" / "emissions-data.js")

    def artifact(self, name: str) -> Path:
        return self.artifacts_dir / name

    def report(self, stage: str) -> Path:
        return self.reports_dir / f"{stage}.json"


# Override precedence (highest first). Documented here so one resolver can be added later.
OVERRIDE_PRECEDENCE = (
    "geocodes/geocode_overrides.json",  # pin coordinates
    "geocodes/affiliation_geocodes.csv",  # Google geocode OK rows
    "geocodes/affiliation_geocodes_manual_01.csv",  # manual / capital fallbacks
    "geocodes/affiliation_display_aliases.json",  # canonical display strings
    "overrides/delegate_organisation_overrides.csv",  # PDF org fixes (applied at PDF→JSON only)
    "overrides/map_excluded_names.txt",  # hide from map
)
