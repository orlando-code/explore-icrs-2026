"""Canonical paths under data/ (single source of truth for the pipeline)."""

from __future__ import annotations

from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATA_ROOT = PROJECT_ROOT / "data"

SOURCES = DATA_ROOT / "sources"
REGISTRY = DATA_ROOT / "registry"
GEOCODES = DATA_ROOT / "geocodes"
OVERRIDES = DATA_ROOT / "overrides"
GEOGRAPHY = DATA_ROOT / "geography"
CACHE = DATA_ROOT / "cache"

# Sources
PROGRAMME_JSON = SOURCES / "programme.json"
ABSTRACTS_JSON = SOURCES / "abstracts.json"
DELEGATES_JSON = SOURCES / "delegates.json"
DELEGATE_PDF = SOURCES / "delegate_list_230726.pdf"
DELEGATES_LAYOUT_TXT = SOURCES / "delegates_layout.txt"

# Person registry
PERSON_REGISTRY_CSV = REGISTRY / "person_registry.csv"
PERSON_ALIASES_CSV = REGISTRY / "person_name_aliases.csv"
PERSON_OVERRIDES_CSV = REGISTRY / "person_registry_overrides.csv"
PERSON_UNMATCHED_CSV = REGISTRY / "person_registry_unmatched.csv"
# Local-only: official offset-registration IDs – never commit.
PERSON_OFFICIAL_IDS_CSV = REGISTRY / "person_registry_official_ids.csv"
CHECK_IN_DELEGATES_CSV = REGISTRY / "delegates_checked_in_with_privacy.csv"

# Affiliation registry
AFFILIATION_REGISTRY_CSV = REGISTRY / "affiliation_registry.csv"
AFFILIATION_ALIASES_CSV = REGISTRY / "affiliation_aliases.csv"
AFFILIATION_OVERRIDES_CSV = REGISTRY / "affiliation_registry_overrides.csv"
AFFILIATION_UNMATCHED_CSV = REGISTRY / "affiliation_registry_unmatched.csv"
AFFILIATION_REVIEWED_CSV = REGISTRY / "affiliation_registry_unmatched_reviewed.csv"

# Geocodes
AFFILIATION_GEOCODES_CSV = GEOCODES / "affiliation_geocodes.csv"
AFFILIATION_GEOCODES_MANUAL_CSV = GEOCODES / "affiliation_geocodes_manual_01.csv"
GEOCODE_OVERRIDES_JSON = GEOCODES / "geocode_overrides.json"
AFFILIATION_DISPLAY_ALIASES_JSON = GEOCODES / "affiliation_display_aliases.json"

# Overrides & review
DELEGATE_ORG_OVERRIDES_CSV = OVERRIDES / "delegate_organisation_overrides.csv"
MAP_EXCLUDED_NAMES_TXT = OVERRIDES / "map_excluded_names.txt"
MAP_EXCLUDED_NAMES_JSON = OVERRIDES / "map_excluded_names.json"
CHECK_IN_OVERRIDES_CSV = OVERRIDES / "check_in_overrides.csv"
DELEGATE_ID_MATCH_REVIEW_GLOB = "delegate_id_match_review_*_merged.csv"

# Geography (emissions choropleth)
COUNTRY_BOUNDARIES_CENTROIDS_JSON = GEOGRAPHY / "country_boundaries_centroids.json"
COUNTRY_CONTINENTS_JSON = GEOGRAPHY / "country_continents.json"
COUNTRY_NEIGHBOURS_JSON = GEOGRAPHY / "country_neighbours.json"
NATIONAL_PER_CAPITA_JSON = GEOGRAPHY / "national_per_capita_co2.json"

# API caches (often gitignored)
TRAVEL_EMISSIONS_CACHE_JSON = CACHE / "travel_emissions_cache.json"
GOOGLE_GEOCODE_CACHE_JSON = CACHE / "google_geocode_cache.json"
REVERSE_GEOCODE_CACHE_JSON = CACHE / "reverse_geocode_cache.json"

# Relative paths for static site / JS exports (from site root)
COUNTRY_BOUNDARIES_REL = "data/geography/country_boundaries.geojson"


def delegate_id_match_review_files(data_dir: Path | None = None) -> list[Path]:
    """Merged delegate-ID review CSVs (newest version wins in consumers)."""
    root = OVERRIDES if data_dir is None else Path(data_dir)
    return sorted(root.glob(DELEGATE_ID_MATCH_REVIEW_GLOB))
