# Delegate ID registration (local only)

Offset registration can require a **delegate ID** (2–5 digits from the welcome email) that must match the selected name. IDs are stored **only on your machine** and on the production API server — they must never appear in the public git repo or static site.

## Export the ID list (local, not committed)

After rebuilding the person registry:

```bash
python scripts/pipeline/build_pipeline.py registry
python scripts/export_delegate_ids_csv.py --output backend/data/delegate_ids.csv
```

This reads `data/registry/person_registry_official_ids.csv` (gitignored) and writes `backend/data/delegate_ids.csv` (also gitignored). Names use `canonical_name` so they match the emissions offset search.

For a tiny local docker smoke test (fake rows only — do not commit the output):

```bash
python scripts/export_delegate_ids_csv.py --sample 3 --output /tmp/delegate_ids.sample.csv
```

## Test locally

### 1. Export IDs and start the API (docker-compose)

```bash
python scripts/export_delegate_ids_csv.py
docker compose up --build -d
```

This runs the API on `http://127.0.0.1:8080` with:

- `REQUIRE_DELEGATE_ID=1`
- `SKIP_TURNSTILE_VERIFY=1` (no Cloudflare Turnstile needed locally)
- `backend/data/delegate_ids.csv` mounted at `/app/data/delegate_ids.csv`

### 2. Point the site at the local API

In `index.html`, uncomment the local meta tags and comment out the Fly URLs:

```html
<meta name="icrs-offset-api" content="http://127.0.0.1:8080/api/offsets" />
<meta name="icrs-contact-api" content="http://127.0.0.1:8080/api/contact" />
```

`icrs-require-delegate-id` should be `content="1"` (already set on this branch).

### 3. Serve the static site

```bash
python3 -m http.server 8000
```

Open `http://127.0.0.1:8000`, go to **Emissions**, search your name, enter your delegate ID, and submit.

Wrong ID for a name returns: *Delegate ID does not match this name.*

## Production deploy (when ready)

1. Run `export_delegate_ids_csv.py` on a secure machine after each registry rebuild.
2. Upload CSV to Fly (volume or secret workflow — do not commit the file).
3. Set Fly secrets/env:
   - `REQUIRE_DELEGATE_ID=1`
   - `DELEGATE_IDS_PATH=/data/delegate_ids.csv`
4. Remove `SKIP_TURNSTILE_VERIFY` (Turnstile must stay enabled in production).
5. Deploy API + static site together.
