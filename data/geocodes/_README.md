# `data/geocodes/`

Affiliation geocoding used by the map and emissions pipeline.


| File                                 | Description                           |
| ------------------------------------ | ------------------------------------- |
| `affiliation_geocodes.csv`           | Primary lat/lon per affiliation key   |
| `affiliation_geocodes_manual_01.csv` | Hand-placed coordinates (edited once) |
| `geocode_overrides.json`             | Location overrides                    |
| `affiliation_display_aliases.json`   | Short display names on map pins       |


Built/updated by `src/geocoding/affiliation_geocodes.py` and `scripts/pipeline/run_affiliation_geocoding.py`. Exported to `js/geocode-overrides.js` on `export-site`.