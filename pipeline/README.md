# ICRS data pipeline

Staged, verifiable rebuild of map and emissions site data from raw sources.

## Quick start

```bash
# Full rebuild (cache-only emissions; no API calls)
python scripts/pipeline/build_pipeline.py all --no-fetch-routes

# Sign-off checklist
python scripts/pipeline/check_pipeline_parity.py

# Preview locally
python3 -m http.server 8000
# → http://localhost:8000
```

Fetch missing travel routes (needs `keys.yaml`):

```bash
python scripts/pipeline/build_pipeline.py emissions
# or: python scripts/pipeline/rebuild_emissions_export.py
```

Refresh Google geocodes for registry affiliations:

```bash
python scripts/pipeline/run_affiliation_geocoding.py
# or: python scripts/pipeline/build_pipeline.py geocode --refresh-geocodes
```

## Architecture

```
data/sources/          → programme.json, abstracts.json, delegates.json, delegate PDF
data/registry/         → person + affiliation registry CSVs
data/geocodes/         → affiliation_geocodes, geocode_overrides, display aliases
data/overrides/        → delegate org overrides, map exclusions, ID match review
data/geography/        → country boundaries, neighbors, national per-capita
data/cache/            → travel_emissions_cache, google geocode cache (often gitignored)

scripts/pipeline/      → build_pipeline.py, export_attendee_site.py, …
scripts/site/          → bundle_static_site.mjs, patch_*.mjs
scripts/deploy/        → deploy_offset_api.sh, push_offsets_db.sh
```

| Module | Role |
|--------|------|
| `pipeline/stages.py` | Stage runners |
| `pipeline/verify.py` | Registry + emissions coverage checks |
| `src/data_paths.py` | Canonical paths under `data/` |
| `src/sources/` | Programme and delegate list loading |
| `src/registry/` | Person (`icrs-p-*`) and affiliation (`icrs-a-*`) registries |
| `src/geocoding/` | Geocode CSVs, Google API, overrides |
| `src/emissions/` | Travel emissions and `emissions-data.js` build |
| `src/geography/` | Country choropleth clustering |
| `src/site/` | Map/talks JS export helpers |

## Scripts (active)

| Script | Purpose |
|--------|---------|
| `scripts/pipeline/build_pipeline.py` | **Main entry** — run stages, write `pipeline/reports/*.json` |
| `scripts/pipeline/export_attendee_site.py` | Map/talks JS (`export-site` stage) |
| `scripts/pipeline/rebuild_emissions_export.py` | Standalone emissions rebuild |
| `scripts/pipeline/run_affiliation_geocoding.py` | Google geocode refresh |
| `scripts/pipeline/check_pipeline_parity.py` | Parity / coverage sign-off |

## Stages

| Stage | What it does | Artifacts |
|-------|----------------|-----------|
| **delegates** | Load or re-parse delegate PDF | `pipeline/artifacts/delegates.csv` |
| **programme** | Load programme snapshot | `pipeline/artifacts/talks.csv` |
| **registry** | Person registry (`icrs-p-*`) | `data/registry/person_registry.csv` |
| **affiliations** | Affiliation registry (`icrs-a-*`) | `data/registry/affiliation_registry.csv` |
| **geocode** | Verify geocode coverage | `pipeline/artifacts/geocoded_attendees.csv` |
| **export-site** | Map JS modules | `js/locations.js`, `js/talks.js`, … |
| **emissions** | Emissions tab data | `js/emissions-data.js`, `pipeline/artifacts/emissions_coverage.csv` |

Each stage writes `pipeline/reports/<stage>.json` with metrics and warnings.

## Traceability

After a full run:

- **Stage reports:** `pipeline/reports/*.json`
- **Intermediate CSVs:** `pipeline/artifacts/`
- **Registries:** `data/registry/person_registry.csv`, `data/registry/affiliation_registry.csv`
- **Coverage:** `pipeline/artifacts/emissions_coverage.csv`
- **Parity:** `python scripts/pipeline/check_pipeline_parity.py`

## Required `data/` layout

Committed inputs for a full rebuild (caches may be local-only):

- **sources/** — `programme.json`, `abstracts.json`, `delegates.json`
- **registry/** — `person_registry.csv`, `person_name_aliases.csv`, `person_registry_overrides.csv`, `person_registry_unmatched.csv`, `affiliation_registry.csv`, `affiliation_aliases.csv`, `affiliation_registry_overrides.csv`, `affiliation_registry_unmatched_reviewed.csv`, `affiliation_registry_unmatched.csv`
- **geocodes/** — `affiliation_geocodes.csv`, `affiliation_geocodes_manual_01.csv`, `geocode_overrides.json`, `affiliation_display_aliases.json`
- **overrides/** — `delegate_organisation_overrides.csv`, `map_excluded_names.txt`, `delegate_id_match_review_04_merged.csv` (latest merged official-ID links)
- **geography/** — `country_boundaries.geojson`, `country_boundaries_centroids.json`, `country_neighbors.json`, `country_continents.json`, `national_per_capita_co2.json`
- **cache/** (often gitignored) — `travel_emissions_cache.json`, `google_geocode_cache.json`, `google_geocode_flags.json`

## Manual overrides

Precedence (highest first) — see `pipeline/config.py`:

1. `geocodes/geocode_overrides.json`
2. `geocodes/affiliation_geocodes.csv`
3. `geocodes/affiliation_geocodes_manual_01.csv`
4. `geocodes/affiliation_display_aliases.json`
5. `overrides/delegate_organisation_overrides.csv`
6. `registry/affiliation_registry_unmatched_reviewed.csv` — see `AFFILIATION_REGISTRY.md`
7. `overrides/map_excluded_names.txt`

## Flags

| Flag | Effect |
|------|--------|
| `--refresh-delegates` | Re-parse delegate PDF |
| `--refresh-geocodes` | Google geocoding API before verify |
| `--no-fetch-routes` | Emissions: cache only |
| `--estimate-emissions` | Re-query all travel routes |

Default emissions: fetch **missing** routes via `fifth-emissions-dev` in `keys.yaml`.

## Related docs

- `PERSON_REGISTRY.md` — person keys and review
- `AFFILIATION_REGISTRY.md` — affiliation keys and geocoding

## Site features outside this pipeline

These committed JS modules are **not** rebuilt by `build_pipeline.py`:

- `js/speaker-profiles.js` — network tab profiles
- `js/talk-similarities.js` — talk similarity sidebar
