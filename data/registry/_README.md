# `data/registry/`

Person and affiliation registries produced by `python scripts/pipeline/build_pipeline.py registry affiliations`.


| File                            | Description                                               |
| ------------------------------- | --------------------------------------------------------- |
| `person_registry.csv`           | One row per person with `person_key`s `icrs-p-*`          |
| `person_name_aliases.csv`       | Mapping name variant to `person_key`                      |
| `person_registry_unmatched.csv`   | **Output only** – review queue (not a pipeline input)     |
| `affiliation_registry.csv`      | One row per affiliation with `affiliation_key` `icrs-a-*` |
| `affiliation_aliases.csv`       | Affiliation string variants                               |
| `*.meta.json`                   | Build metrics                                             |


**Local only (gitignored):** `person_registry_official_ids.csv` – official offset-registration IDs.

See [pipeline/PERSON_REGISTRY.md](../../pipeline/PERSON_REGISTRY.md) and [pipeline/AFFILIATION_REGISTRY.md](../../pipeline/AFFILIATION_REGISTRY.md).
