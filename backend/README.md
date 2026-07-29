# Offset registration API

Small stdlib-only HTTP service that stores self-reported travel offsets for the emissions tab. SQLite on a persistent volume; no extra Python dependencies.

## Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/offsets` | Aggregate counts only — `{ counts: { speakers, delegates }, totals: { speakers, delegates } }` |
| `POST` | `/api/offsets` | Body `{ "id": "offset-…", "name": "…", "affiliation_key": "…", "pool": "speakers", "cf-turnstile-response": "…" }` — idempotent |
| `POST` | `/api/contact` | Body `{ "name": "…", "affiliation": "…", "cf-turnstile-response": "…" }` — verified email lookup |
| `GET` | `/api/admin/export` | Full ledger + audit trail. Needs `Authorization: Bearer $ADMIN_TOKEN`; `404` when unset |
| `GET` | `/health` | Liveness check |

Attendee ids must match `offset-[0-9a-f]{8}` (same format as the frontend).

### Nothing about individuals is published

Attendee ids are a hash of a public name, so publishing them published who had and had not offset. `GET /api/offsets` therefore returns only counts: a total per pool, and a tally per affiliation so the map can shade a location.

`affiliation_key` is whatever `affiliationMapKey()` in `js/utils.js` produces. The server groups by it without parsing it, so the two cannot drift apart. `pool` is `speakers` or `delegates`, matching the site's non-speaker toggle; speakers are counted in both views. Rows written before this change have neither field: they still count toward the total, they just cannot shade a location.

A visitor's own registration is remembered in their browser's local storage, which is the only reason the form can still say "you registered this".

## Run locally (Python)

From the **repo root** (not inside `backend/`):

```bash
python backend/offset_api.py --port 8787
```

Set in `index.html` while developing:

```html
<meta name="icrs-offset-api" content="http://127.0.0.1:8787/api/offsets" />
```

## Run locally (Docker Compose)

From the **repo root**:

```bash
docker compose up --build
```

API at `http://localhost:8080/api/offsets`. Data persists in a Docker volume.

## Deploy to Railway (recommended)

No Fly.io CLI needed. Railway uses a different tool from Concourse’s `fly` command (which is what errors if you run `fly launch` on many university machines).

1. Push this repo to GitHub.
2. Open [railway.app](https://railway.app) → **New project** → **Deploy from GitHub repo**.
3. Select this repository.
4. In service **Settings** → **Root directory**, set `backend`.
5. In **Variables**, add:
   - `ALLOWED_ORIGINS` = `https://orlando-codes.com,https://www.orlando-codes.com,https://orlando-code.github.io,http://localhost:8000,http://127.0.0.1:8000`
   - `OFFSET_DB_PATH` = `/data/offsets.db`
6. In **Volumes**, add a volume mounted at `/data` (so SQLite survives redeploys).
7. **Settings** → **Networking** → **Generate domain**.
8. Copy the public URL and set `index.html`:

```html
<meta name="icrs-offset-api" content="https://YOUR-APP.up.railway.app/api/offsets" />
```

Redeploy GitHub Pages after updating the meta tag.

## Deploy with Docker (any VPS)

On a server with Docker installed, clone the repo and run from the repo root:

```bash
docker compose up -d --build
```

Put nginx/Caddy in front with HTTPS, or expose port 8080 behind your firewall. Point the `icrs-offset-api` meta tag at `https://your-server/api/offsets` (adjust reverse-proxy path if needed).

## Inspect, hold, and withdraw registrations

Rows are never deleted. Each one has a status — `published`, `pending` (held for review), or `revoked` — and every change appends an audit event, so a suspect batch can be excluded from the totals without losing the record that it happened. Any command that changes the database snapshots it first, into `snapshots/` beside the database file.

```bash
python scripts/manage_offset_registrations.py stats                  # statuses + rate per hour
python scripts/manage_offset_registrations.py list --status pending  # the review queue
python scripts/manage_offset_registrations.py history offset-bdc15009
python scripts/manage_offset_registrations.py approve offset-bdc15009
python scripts/manage_offset_registrations.py revoke offset-bdc15009 --reason spam
```

Point `OFFSET_DB_PATH` at the production volume (or run it inside the deployed container) to manage live rows.

### If registrations spike

Once more than `REVIEW_THRESHOLD_PER_HOUR` registrations arrive in an hour, new rows are stored as `pending` instead of `published`. The visitor is still thanked and nothing is lost, but the public totals stop moving until someone looks. `registration_held_for_review` appears in the logs when this trips.

`stats` shows the per-hour rate and the busiest callers as salted digests. To withdraw a burst, preview it and then apply:

```bash
python scripts/manage_offset_registrations.py revoke-matching --client 49e8159
python scripts/manage_offset_registrations.py revoke-matching --client 49e8159 --yes --reason "scripted burst"
python scripts/manage_offset_registrations.py revoke-matching --since 2026-08-01T12:00:00 --yes
```

Without `--yes` it only lists what it would touch.

## Back up the ledger

The database lives on one Fly volume, so it is one lost volume away from gone. Set an export token, then pull the whole ledger — registrations and audit trail — somewhere else:

```bash
fly secrets set ADMIN_TOKEN="$(openssl rand -hex 32)"

ADMIN_TOKEN=… python scripts/backup_offsets.py \
    --url https://icrs-offset-api.fly.dev/api/admin/export \
    --dir ~/OneDrive/icrs-offset-backups
```

Each run writes a timestamped JSON snapshot, never overwriting an existing one, and prunes to the last `--keep` (default 30). Snapshots contain names and caller digests, so **the destination must be private** — the default `backups/` directory is gitignored. Schedule it (`crontab -e`, daily) for the offsite copy to be worth anything.

Fly's own daily volume snapshots are a second layer; `fly volumes snapshots list offset_data` lists them.

Without a token you can still copy the database off and snapshot it locally:

```bash
fly ssh sftp get /data/offsets.db ./offsets-live.db
python scripts/backup_offsets.py --db ./offsets-live.db
```

### Restore

`import_offset_registrations.py` reads a backup snapshot back in, preserving each row's original timestamp, status, and pool:

```bash
python scripts/import_offset_registrations.py backups/offsets-20260801T030000Z.json
```

It only inserts ids that are missing, so running it against a live database is safe — it tops up rather than overwrites.

## Verified email lookup

Emails are **not** in the static site. Export verified addresses from your local cache, then bake them into the API image:

```bash
.venv/bin/python scripts/export_contact_api_data.py
```

This writes `backend/data/contacts.json` (gitignored). Rebuild and redeploy the backend so Fly picks up the new file.

The network tab shows a **Show verified email** button for profiles marked `verified` in the cache. The browser sends a Turnstile token to `POST /api/contact`; the server verifies it with Cloudflare, then returns one email.

## Environment

| Variable | Default | Purpose |
|----------|---------|---------|
| `OFFSET_DB_PATH` | `data/offsets.db` | SQLite file path |
| `ALLOWED_ORIGINS` | GitHub Pages + localhost | Comma-separated CORS origins |
| `PORT` | `8080` | Listen port (Railway sets this automatically) |
| `TURNSTILE_SECRET` | *(required for POST)* | Cloudflare Turnstile secret key for `POST /api/offsets` siteverify |
| `CONTACTS_PATH` | `data/contacts.json` | Verified email store for `POST /api/contact` |
| `CLIENT_IP_HEADER` | `Fly-Client-IP` | Header the rate limiter reads the caller address from. **Must be one your proxy overwrites** |
| `REQUIRE_ORIGIN` | `1` | Reject `POST` without an allowed `Origin`. Set `0` only to test with curl |
| `CLIENT_HINT_SALT` | *(random per process)* | Salt for the stored caller digests. Set it to keep hints comparable across restarts |
| `REVIEW_THRESHOLD_PER_HOUR` | `60` | Above this many registrations in an hour, new rows are held for review instead of published. `0` disables the hold |
| `ADMIN_TOKEN` | *(unset — route 404s)* | Bearer token for `GET /api/admin/export`. Keep it as long and boring as any other secret |

### Rate limiting and the caller address

`X-Forwarded-For` is deliberately ignored, because any client can send it and would otherwise choose its own rate-limit bucket. The limiter reads `CLIENT_IP_HEADER` — a header the platform overwrites (`Fly-Client-IP` on Fly, `CF-Connecting-IP` behind Cloudflare) — and falls back to the socket peer address.

**Behind your own nginx/Caddy**, set `CLIENT_IP_HEADER` to a header your proxy sets and strips from inbound requests, or set it to the empty string to use the socket peer.

Each endpoint has a per-caller hourly budget *and* a ceiling across all callers, so a pool of rotating addresses cannot turn the per-caller limits into an unlimited one. Rate-limit rejections and contact lookups are logged as JSON to stdout; addresses appear only as salted 16-character digests.

`POST /api/offsets` requires a valid Turnstile token in `cf-turnstile-response` (or `turnstile_token`). The frontend offset registration form includes the widget; set `TURNSTILE_SECRET` on Fly/Railway before deploying. Without it, both `POST` endpoints return `503` rather than accepting anything.

```bash
# Fly.io
fly secrets set TURNSTILE_SECRET=your-secret-here

# Railway: add TURNSTILE_SECRET in service Variables
```

## Note on `fly` vs Fly.io

If `fly launch` prints errors about pipelines and workers, your shell has **Concourse CI’s** `fly` binary, not [Fly.io](https://fly.io). Either install Fly.io as `flyctl` (`brew install flyctl`) or use Railway / Docker Compose above instead.
