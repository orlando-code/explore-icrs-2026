# ICRS 2026 speaker affiliations

Interactive (emissions) map and co-authorship network for ICRS 2026 speakers.

**Live site:** https://orlando-codes.com/icrs2026-explorer/
<!-- 
Regenerate speaker profile/contact links for the network tab:

```bash
# Refresh failed / outdated lookups (parallel by default)
python scripts/export_speaker_profiles.py --retry-failed

# Tune concurrency if you hit rate limits (OpenAlex, DuckDuckGo)
python scripts/export_speaker_profiles.py --retry-failed --workers 4

# Normalize cache after manual edits (fix JSON, set verified fields)
python scripts/normalize_speaker_profiles_cache.py

# Re-export JS from cache only (sanitizes weak auto-scraped emails)
python scripts/sanitize_export_profiles.py
# or, if your Python env has project deps installed:
python scripts/export_speaker_profiles.py --export-only

# Mark good manual email fixes as verified (skipped by future lookups)
python scripts/mark_verified_profiles.py
```

Add `"verified": true` to any entry in `data/speaker_profiles_cache.json` to protect manual edits permanently.

## Offset registration API

The emissions tab shares offset pledges through a small SQLite-backed API in `backend/offset_api.py`. Only aggregate counts are published — never a list of who registered. Rows are held for review rather than published when registrations spike, and `scripts/manage_offset_registrations.py` and `scripts/backup_offsets.py` handle inspection, withdrawal, and offsite backups. See [backend/README.md](backend/README.md).

**Quick start (local):** from the repo root, run `docker compose up --build` or `python backend/offset_api.py --port 8787`.

**Production:** deploy via [Railway](https://railway.app) (GitHub connect, root directory `backend`, volume on `/data`) — see [backend/README.md](backend/README.md). Do not use `fly launch` unless you have Fly.io’s `flyctl` installed; many systems ship Concourse’s unrelated `fly` command instead.

Set the API URL in `index.html`:

```html
<meta name="icrs-offset-api" content="https://your-api.example.com/api/offsets" />
``` -->
