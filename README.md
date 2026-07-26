# ICRS 2026 speaker affiliations

Interactive map and co-authorship network for ICRS 2026 speakers, geocoded by affiliation and centred on Auckland.

**Live site:** https://orlando-codes.com/icrs2026-explorer/ (also https://orlando-code.github.io/explore-icrs-2026/)

Regenerate speaker profile/contact links for the network tab:

```bash
# Refresh failed / outdated lookups (parallel by default)
python scripts/export_speaker_profiles.py --retry-failed

# Tune concurrency if you hit rate limits (OpenAlex, DuckDuckGo)
python scripts/export_speaker_profiles.py --retry-failed --workers 4

# Re-export JS from cache only
python scripts/export_speaker_profiles.py --export-only
```

## Offset registration API

The emissions tab shares offset pledges through a small SQLite-backed API in `backend/offset_api.py`.

**Quick start (local):** from the repo root, run `docker compose up --build` or `python backend/offset_api.py --port 8787`.

**Production:** deploy via [Railway](https://railway.app) (GitHub connect, root directory `backend`, volume on `/data`) — see [backend/README.md](backend/README.md). Do not use `fly launch` unless you have Fly.io’s `flyctl` installed; many systems ship Concourse’s unrelated `fly` command instead.

Set the API URL in `index.html`:

```html
<meta name="icrs-offset-api" content="https://your-api.example.com/api/offsets" />
```
