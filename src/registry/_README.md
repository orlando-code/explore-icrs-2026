# `src/registry/`

Build and query person (`icrs-p-*`) and affiliation (`icrs-a-*`) registries.


| Module                    | Role                                                                 |
| ------------------------- | -------------------------------------------------------------------- |
| `person_registry.py`      | Person registry build/save                                           |
| `affiliation_registry.py` | Affiliation registry build                                           |
| `key_resolution.py`       | Runtime `person_key` / `affiliation_key` resolution and CSV enrich   |
| `registry_export.py`      | Registry-backed map talk rows                                        |
| `affiliation_lookup.py`   | Affiliation key resolution                                           |


`key_resolution.py` is the single source of truth for identity at export time. Downstream code should call `resolve_person_key()` / `resolve_affiliation_key()` (or `get_registry_key_resolver()`) instead of deduplicating by bare display name. Ambiguous bare names (homonyms) are excluded from automatic alias lookup.

Stage: `python scripts/pipeline/build_pipeline.py registry affiliations`