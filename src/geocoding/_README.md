# `src/geocoding/`

Resolve affiliation strings to coordinates to show locations on map.


| Module                    | Role                                         |
| ------------------------- | -------------------------------------------- |
| `affiliation_geocodes.py` | CSV geocode table, overrides export to JS    |
| `geocode.py`              | Display names and canonical affiliation keys |
| `google_geocode.py`       | Google Geocoding API                         |
| `geocode_refresh.py`      | Batch refresh into `data/geocodes/`          |
| `capital_coords.py`       | Country-capital fallbacks                    |
| `foreign_delegate.py`     | Foreign-delegate routing hints               |


