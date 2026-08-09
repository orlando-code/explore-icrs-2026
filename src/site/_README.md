# `src/site/`

Helpers that write static JS modules under `js/`.

| Module | Role |
|--------|------|
| `plot_utils.py` | `locations.js` (`export_attendee_site_data`) |
| `talks_export.py` | `talks.js` catalogue |
| `map_exclusions.py` | `map-excluded-names.js` |
| `export_progress.py` | CLI progress for long exports |

Exports attach `person_key` and `affiliation_key` from the registry resolver. Network co-authorship and `talk_titles_by_person_key` in `locations.js` are keyed by `person_key` so homonyms (same display name, different affiliations) stay distinct.

Orchestrated by `scripts/pipeline/export_attendee_site.py` (`export-site` stage).
