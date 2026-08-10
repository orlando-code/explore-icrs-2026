# Source modules (`src/`)

Python library for the data pipeline and static site exports. Entry scripts live under `scripts/pipeline/`.

| Path | Role |
|------|------|
| `data_paths.py` | Canonical paths under `data/` |
| [util/](util/) | Shared helpers (`json_io`, `geo_math`, `console`) |
| [sources/](sources/) | Programme and delegate list loading |
| [registry/](registry/) | Person and affiliation registries; `key_resolution.py` |
| [geocoding/](geocoding/) | Affiliation geocoding and overrides |
| [emissions/](emissions/) | Travel emissions and `emissions-data.js` |
| [geography/](geography/) | Country boundaries, neighbours, clusters |
| [site/](site/) | Map/talks JS export helpers |
| [profiles/](profiles/) | Speaker profiles and talk similarity |
