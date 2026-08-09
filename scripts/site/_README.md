# `scripts/site/`

Static site bundling and post-export patches. Run from the repo root.

| Script | Purpose |
|--------|---------|
| `bundle_static_site.mjs` | Copy deployable HTML/CSS/JS/data into a target directory for hosting under a subpath (e.g. `/icrs2026-explorer/`). Patches `index.html` base URLs. |
| `patch_locations_connections.mjs` | Patch `js/locations.js` with `connection_count` and recalculated great-circle distances from Auckland. |
| `patch_speaker_talk_titles.mjs` | **Deprecated** – `export_attendee_site.py` writes `talk_titles_by_person_key` directly. |

These are **not** run automatically by `build_pipeline.py` – invoke after site export when needed.

See [js/_README.md](../../js/_README.md) for which JS modules are pipeline-built vs hand-maintained.
