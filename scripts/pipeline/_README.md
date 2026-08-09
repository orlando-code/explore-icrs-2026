# `scripts/pipeline/`

Data pipeline entry points. Run from the repo root.

| Script | Purpose |
|--------|---------|
| `build_pipeline.py` | Main orchestrator – run stages (`sources`, `registry`, `affiliations`, `geocodes`, `site`, `emissions`, …) end-to-end or selectively. Writes `pipeline/reports/<stage>.json`. |
| `export_attendee_site.py` | Export static JS for the map site: `js/locations.js`, `js/talks.js`, `js/map-excluded-names.js`, `js/non-speaking-delegates.js`, geocode overrides. |
| `rebuild_emissions_export.py` | Rebuild `js/emissions-data.js` from registry geocodes and the travel-emissions cache / emissions.dev API. |
| `run_affiliation_geocoding.py` | Geocode missing affiliations via Google Maps (cached). Use `--dry-run` to list targets only. |
| `build_capital_coords_data.py` | Build `data/geography/country_capitals.json` and `us_state_capitals.json` from curated seeds + Nominatim. |
| `check_pipeline_parity.py` | Verification summary – registry coverage, emissions coverage, `locations.js` stats for sign-off. |

**Typical full rebuild:**

```bash
python scripts/pipeline/build_pipeline.py all --no-fetch-routes
```

See [pipeline/_README.md](../../pipeline/_README.md).
