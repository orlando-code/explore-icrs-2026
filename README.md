# ICRS 2026 speaker affiliations

Interactive (emissions) map and co-authorship network for ICRS 2026 speakers.

**Live site:** https://orlando-codes.com/explore-icrs-2026/ (also https://orlando-code.github.io/explore-icrs-2026/)

## Data pipeline

Rebuild map and emissions data from registries:

```bash
python scripts/pipeline/build_pipeline.py all --no-fetch-routes
python scripts/pipeline/check_pipeline_parity.py
python3 -m http.server 8000   # preview at http://localhost:8000
```

See [pipeline/README.md](pipeline/README.md) for stages, overrides, and API keys.

## Network tab profiles

Committed `js/speaker-profiles.js` is the source of truth for the network tab.

## Offset API

See [backend/README.md](backend/README.md). Deploy helpers live under `scripts/deploy/`.
