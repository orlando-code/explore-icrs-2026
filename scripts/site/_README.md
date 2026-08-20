# `scripts/site/`

Static site bundling. Run from the repo root.

| Script | Purpose |
|--------|---------|
| `bundle_static_site.mjs` | Copy deployable HTML/CSS/JS/data into a target directory for hosting under a subpath (e.g. `/icrs2026-explorer/`). Patches `index.html` base URLs. |

`export_attendee_site.py` already writes `connection_count` and Auckland distances into `js/locations.js` — no post-export patch step is required.

See [js/_README.md](../../js/_README.md) for which JS modules are pipeline-built vs hand-maintained.
