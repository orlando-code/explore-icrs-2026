# ICRS Explorer data pipeline

Staged rebuild of map and emissions site data from raw sources.

**Related docs in this folder:** `PERSON_REGISTRY.md`, `AFFILIATION_REGISTRY.md`, `METHODOLOGY.md`  
**Front-end bundles:** [js/_README.md](../js/_README.md) (static builds vs codebase)  
**Data layout:** [data/_README.md](../data/_README.md)

---

If you're interested in how this all came together, feel free to have a play! You'll need to get the necessary source files (see [data/_README.md](../data/_README.md)) in the right places first.

## Quick start

```bash
# Full rebuild (no API calls: geocoding and emissions data from cache)
python scripts/pipeline/build_pipeline.py all --no-fetch-routes

# Sign-off checklist
python scripts/pipeline/check_pipeline_parity.py

# Preview locally
python3 -m http.server 8000
# view on http://localhost:8000
```

Fetch missing emissions estimates (requires `keys.yaml` in the repository root with valid API keys for [emissions.dev](https://emissions.dev); see `keys-example.yaml`): 

```bash
python scripts/pipeline/build_pipeline.py emissions
# equivalent to: python scripts/pipeline/rebuild_emissions_export.py
```

Refresh Google geocodes for registry affiliations:

```bash
python scripts/pipeline/run_affiliation_geocoding.py
# equivalent to: python scripts/pipeline/build_pipeline.py geocode --refresh-geocodes
```



## Architecture

```
data/sources/          -> programme.json, abstracts.json, delegates.json, delegate PDF
data/registry/         -> person + affiliation registry CSVs
data/geocodes/         -> affiliation_geocodes, geocode_overrides, display aliases
data/overrides/        -> delegate organisation overrides, map exclusions, ID match review
data/geography/        -> country boundaries, neighbors, national per-capita
data/cache/            -> travel_emissions_cache, google geocode cache (often gitignored)

scripts/pipeline/      -> build_pipeline.py, export_attendee_site.py, …
scripts/site/          -> bundle_static_site.mjs, patch_*.mjs
scripts/deploy/        -> deploy_offset_api.sh, push_offsets_db.sh
```


| Module               | Role                                                        |
| -------------------- | ----------------------------------------------------------- |
| `pipeline/stages.py` | Stage runners                                               |
| `pipeline/verify.py` | Registry + emissions coverage checks                        |
| `src/data_paths.py`  | Canonical paths under `data/`                               |
| `src/sources/`       | Programme and delegate list loading                         |
| `src/registry/`      | Person (`icrs-p-*`) and affiliation (`icrs-a-*`) registries; `key_resolution.py` for runtime identity |
| `src/geocoding/`     | Geocode CSVs, Google API, overrides                         |
| `src/emissions/`     | Travel emissions and `emissions-data.js` build              |
| `src/geography/`     | Country choropleth clustering                               |
| `src/site/`          | Map/talks JS export helpers                                 |




## Scripts (active)


| Script                                          | Purpose                                                      |
| ----------------------------------------------- | ------------------------------------------------------------ |
| `scripts/pipeline/build_pipeline.py`            | **Main entry** – run stages, write `pipeline/reports/*.json` |
| `scripts/pipeline/export_attendee_site.py`      | Map/talks JS (`export-site` stage)                           |
| `scripts/pipeline/rebuild_emissions_export.py`  | Standalone emissions rebuild                                 |
| `scripts/pipeline/run_affiliation_geocoding.py` | Google geocode refresh                                       |
| `scripts/pipeline/check_pipeline_parity.py`     | Parity / coverage sign-off                                   |




## Stages


| Stage            | What it does                      | Artifacts                                                           |
| ---------------- | --------------------------------- | ------------------------------------------------------------------- |
| **delegates**    | Load or re-parse delegate PDF     | `pipeline/artifacts/delegates.csv`                                  |
| **programme**    | Load programme snapshot           | `pipeline/artifacts/talks.csv`                                      |
| **registry**     | Person registry (`icrs-p-`*)      | `data/registry/person_registry.csv`; enriches `talks.csv` / `delegates.csv` with `person_key` |
| **affiliations** | Affiliation registry (`icrs-a-`*) | `data/registry/affiliation_registry.csv`                            |
| **geocode**      | Verify geocode coverage           | `pipeline/artifacts/geocoded_attendees.csv`                         |
| **export-site**  | Map JS modules                    | `js/locations.js`, `js/talks.js`, …                                 |
| **emissions**    | Emissions tab data                | `js/emissions-data.js`, `pipeline/artifacts/emissions_coverage.csv` |


Each stage writes `pipeline/reports/<stage>.json` with metrics and warnings.

## Traceability

After a full run:

- **Stage reports:** `pipeline/reports/*.json`
- **Intermediate CSVs:** `pipeline/artifacts/`
- **Registries:** `data/registry/person_registry.csv`, `data/registry/affiliation_registry.csv`
- **Coverage:** `pipeline/artifacts/emissions_coverage.csv`
- **Parity:** `python scripts/pipeline/check_pipeline_parity.py`



## Required `data/` layout

Committed inputs for a full rebuild (caches may be local-only). **Regenerated** means `python scripts/pipeline/build_pipeline.py …` can recreate the file from upstream inputs without re-downloading sources. **Captured** means you need EventsAir / delegate PDF capture (or `--refresh-delegates`). **Static** assets are checked in and not produced by the pipeline.

| Path | Role | How to obtain |
|------|------|----------------|
| **sources/** `programme.json`, `abstracts.json`, `delegates.json` | Raw conference capture | **Captured** from EventsAir + delegate PDF (`--refresh-delegates` re-parses PDF only) |
| **registry/** `person_registry.csv`, `person_name_aliases.csv`, `affiliation_registry.csv`, `affiliation_aliases.csv` | Canonical keys | **Regenerated** – `build_pipeline.py registry affiliations` |
| **registry/** `person_registry_unmatched.csv`, `affiliation_registry_unmatched.csv` | Review queues | **Regenerated output** – written by registry stages; **not** read back as inputs |
| **registry/** `affiliation_registry_overrides.csv`, `affiliation_registry_unmatched_reviewed.csv` | Manual affiliation fixes | Hand-edited; affiliation overrides are inputs to rebuild |
| **geocodes/** `affiliation_geocodes.csv` | Google geocode results | **Regenerated** with `--refresh-geocodes` (needs API key) or from committed CSV |
| **geocodes/** `affiliation_geocodes_manual_01.csv`, `geocode_overrides.json`, `affiliation_display_aliases.json` | Manual geocode fixes | Hand-edited |
| **overrides/** `delegate_organisation_overrides.csv`, `map_excluded_names.txt` | Org + map exclusions | Hand-edited |
| **overrides/** `delegate_id_match_review_*_merged.csv` | Official-ID name links | Hand-curated; latest merged file is gitignored (IDs must stay local) |
| **geography/** `country_boundaries.geojson`, `country_boundaries_centroids.json`, `country_neighbors.json`, `country_continents.json`, `national_per_capita_co2.json` | Choropleth + clustering | **Static** – not regenerated by `build_pipeline.py` |
| **cache/** `travel_emissions_cache.json`, `google_geocode_cache.json`, … | API caches | Local-only; rebuilt on demand |

Uncorrected registry/geocode CSVs can be regenerated from committed `sources/` plus hand-maintained overrides; you do **not** need to re-download programme/delegate JSON if those files are already present.



## Manual overrides

Precedence (highest first) – see `pipeline/config.py`:

1. `geocodes/geocode_overrides.json`
2. `geocodes/affiliation_geocodes.csv`
3. `geocodes/affiliation_geocodes_manual_01.csv`
4. `geocodes/affiliation_display_aliases.json`
5. `overrides/delegate_organisation_overrides.csv`
6. `registry/affiliation_registry_unmatched_reviewed.csv` – see `AFFILIATION_REGISTRY.md`
7. `overrides/map_excluded_names.txt`



## Flags


| Flag                   | Effect                             |
| ---------------------- | ---------------------------------- |
| `--refresh-delegates`  | Re-parse delegate PDF              |
| `--refresh-geocodes`   | Google geocoding API before verify |
| `--no-fetch-routes`    | Emissions: cache only              |
| `--estimate-emissions` | Re-query all travel routes         |


Default emissions: fetch **missing** routes via `fifth-emissions-dev` in `keys.yaml`.

## Related docs

- `PERSON_REGISTRY.md` – person keys and review
- `AFFILIATION_REGISTRY.md` – affiliation keys and geocoding



## Site features outside this pipeline

These committed JS modules are **not** rebuilt by `build_pipeline.py` – see [js/_README.md](../js/_README.md):

- `js/speaker-profiles.js` – static build (network tab profiles)
- `js/talk-similarities.js` – static build (talk similarity sidebar)

