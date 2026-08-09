# Front-end modules (`js/`)

ES modules loaded by `index.html`. See [pipeline/README.md](../pipeline/README.md) for rebuild commands.

Person identity in the UI uses registry `person_key` (`icrs-p-*`) end-to-end: generated bundles include `person_key` on speakers/delegates, `utils.js` dedupes search by key, and `offset-tracker.js` uses `attendeeDedupeKey(name, affiliation)` for homonym-safe emissions lookup. Aliases ship in `non-speaking-delegates.js` as `DELEGATE_PERSON_KEY_ALIASES`.

## Static builds (generated – do not edit)

| File | Built by |
|------|----------|
| `locations.js` | `scripts/pipeline/export_attendee_site.py` |
| `talks.js` | same (`export_talks_catalog`) |
| `non-speaking-delegates.js` | same |
| `geocode-overrides.js` | same |
| `map-excluded-names.js` | same |
| `emissions-data.js` | `scripts/pipeline/rebuild_emissions_export.py` |
| `speaker-profiles.js` | speaker profile export (`src/profiles/speaker_profiles.py`) |
| `talk-similarities.js` | talk similarity export (`src/profiles/talk_similarity_build.py`) |

Optional post-export patches: `scripts/site/patch_*.mjs` (connections, talk titles on `locations.js`).

## Hand-maintained source (edit these)

| File | Role |
|------|------|
| `app.js` | Tab shell, search, map/network/emissions wiring |
| `map.js` | Affiliation map tab |
| `network.js` | Co-authorship network tab |
| `emissions-view.js` | Emissions map and fair-budget UI |
| `offset-tracker.js` | Offset pledge form (calls Fly API); homonym-safe attendee keys |
| `country-choropleth.js` | Country choropleth layer |
| `config.js` | Base path and API URLs from `index.html` meta tags |
| `utils.js` | Shared map/search helpers; `resolveDelegatePersonKey`, search dedupe by `person_key` |
| `talk-similarity.js` | Lookup helpers over `talk-similarities.js` data |
| `celebration.js` | Map pin celebration animation |
| `more.js` | “More” tab (QR, links) |
