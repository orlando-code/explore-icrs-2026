# `src/geocoding/`

Resolve affiliation strings to coordinates to show locations on map.


| Module                    | Role                                         |
| ------------------------- | -------------------------------------------- |
| `affiliation_geocodes.py` | CSV geocode table, overrides export to JS    |
| `geocode.py`              | Display names and canonical affiliation keys |
| `google_geocode.py`       | Google Geocoding API                         |
| `geocode_refresh.py`      | Batch refresh into `data/geocodes/`          |
| `capital_data.py`         | Load ISO2 capitals from `data/geography/`    |
| `capital_coords.py`       | Capital fallback resolution and mismatch rules |
| `foreign_delegate.py`     | Foreign-delegate routing hints               |

## Capital fallback

When institute geocoding (CSV, overrides, Google) does not return coordinates, the
pipeline falls back to **country or US-state capitals** loaded from:

- `data/geography/country_capitals.json` — keyed by ISO 3166-1 alpha-2
- `data/geography/us_state_capitals.json` — US states and territories

Regenerate with:

```bash
python scripts/pipeline/build_capital_coords_data.py
```

Curated seed coordinates in the build script cover conference delegate countries;
Nominatim fills the remaining ISO codes (cached in `data/cache/capital_geocode_cache.json`).

If a delegate-list country has a known ISO code but no capital record, lookup raises
`CapitalCoordsError` instead of failing silently. Manual pin overrides in
`data/geocodes/geocode_overrides.json` still take precedence over capital fallback.

