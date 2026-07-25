# Offset registration API

Small stdlib-only HTTP service that stores self-reported travel offsets for the emissions tab. SQLite on a persistent volume; no extra Python dependencies.

## Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/offsets` | `{ registrations: string[], count: number }` |
| `POST` | `/api/offsets` | Body `{ "id": "offset-…", "name": "…" }` — idempotent |
| `GET` | `/health` | Liveness check |

Attendee ids must match `offset-[0-9a-f]{8}` (same format as the frontend).

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
   - `ALLOWED_ORIGINS` = `https://orlando-code.github.io,http://localhost:8000,http://127.0.0.1:8000`
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

## Import existing registrations

```bash
python scripts/import_offset_registrations.py
```

Reads `data/offset-registrations.json` into the local SQLite database.

## Environment

| Variable | Default | Purpose |
|----------|---------|---------|
| `OFFSET_DB_PATH` | `data/offsets.db` | SQLite file path |
| `ALLOWED_ORIGINS` | GitHub Pages + localhost | Comma-separated CORS origins |
| `PORT` | `8080` | Listen port (Railway sets this automatically) |

## Note on `fly` vs Fly.io

If `fly launch` prints errors about pipelines and workers, your shell has **Concourse CI’s** `fly` binary, not [Fly.io](https://fly.io). Either install Fly.io as `flyctl` (`brew install flyctl`) or use Railway / Docker Compose above instead.
