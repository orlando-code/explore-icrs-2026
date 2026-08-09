# `src/emissions/`

Travel emissions estimates and the emissions tab static bundle.


| Module                         | Role                                                    |
| ------------------------------ | ------------------------------------------------------- |
| `travel_emissions.py`          | Route cache, CO₂e estimates, `emissions-data.js` export |
| `emissions_build.py`           | Orchestrates emissions pipeline stage                   |
| `emissions_site_enrichment.py` | Join emissions to site locations                        |
| `origin_country.py`            | Delegate origin country inference                       |


Attendee legs and search dedupe use `person_key` (with affiliation-aware fallback via `delegate_person_key()`) so homonyms appear as separate attendees in the emissions tab.

Stage: `python scripts/pipeline/rebuild_emissions_export.py`