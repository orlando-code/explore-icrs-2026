# Data directory

Inputs and registries for the pipeline. Paths are defined in `src/data_paths.py`.


| Subdirectory             | Purpose                                                      |
| ------------------------ | ------------------------------------------------------------ |
| [sources/](sources/)     | Programme snapshot, abstracts, delegate list JSON            |
| [registry/](registry/)   | Person (`icrs-p-*`) and affiliation (`icrs-a-*`) registries  |
| [geocodes/](geocodes/)   | Affiliation coordinates and display/geocode overrides        |
| [geography/](geography/) | Country boundaries, neighbours, choropleth reference data     |
| [overrides/](overrides/) | Manual fixes (orgs, map exclusions, ID match review – local) |
| `cache/`                 | API caches (gitignored, local only)                          |


Can be entirely rebuilt via `python scripts/pipeline/build_pipeline.py all --no-fetch-routes`.