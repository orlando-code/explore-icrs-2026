# Free deployment walkthrough (Fly.io)

Deploy the offset API in the cloud for **$0** (within Fly’s free allowance). Your laptop can be off; GitHub Pages stays static; the API runs on Fly’s servers.

**Important:** use `flyctl`, not `fly`. On many Macs `fly` is Concourse CI and will not work.

## What you need

- GitHub repo with this project pushed
- A credit/debit card for Fly account verification (not charged if you stay within free limits)
- ~20 minutes once

## Step 1 — Install Fly’s CLI

```bash
brew install flyctl
brew link --overwrite flyctl
```

Homebrew installs `flyctl` but may **fail to link** if you already have Concourse’s `fly` cask at `/opt/homebrew/bin/fly`. The `brew link --overwrite flyctl` step fixes that.

If `flyctl` is still “command not found”, use the full path once:

```bash
/opt/homebrew/Cellar/flyctl/*/bin/flyctl version
```

Or add a symlink:

```bash
ln -sf "$(brew --prefix flyctl)/bin/flyctl" /opt/homebrew/bin/flyctl
```

Check you have the right tool:

```bash
which flyctl
flyctl version
```

You should see `flyctl v0.x.x`. After linking, `fly` also runs Fly.io (not Concourse). Do **not** use bare `fly` if you still need Concourse — use `flyctl` only.

Do **not** run Concourse’s `fly launch` — always use **`flyctl`** for Fly.io.

## Step 2 — Log in to Fly

```bash
flyctl auth login
```

Browser opens; sign up or sign in.

## Step 3 — Create the app (from `backend/`)

```bash
cd backend
flyctl launch --no-deploy
```

When prompted:

- **App name:** `icrs-offset-api` (or pick another unique name — you’ll use it in the URL)
- **Region:** Sydney (`syd`) if offered
- **Postgres / Redis:** No
- **Tweak settings:** accept defaults if `fly.toml` is already present

If the app name is taken, choose e.g. `icrs-offset-api-rt582` and note it for the meta tag URL.

## Step 4 — Create persistent storage

Registrations must survive redeploys:

```bash
flyctl volumes create offset_data --region syd --size 1
```

`offset_data` must match `source` in `fly.toml` → `[mounts]`.

## Step 5 — Deploy

```bash
flyctl deploy
```

First build takes a few minutes. When done:

```bash
flyctl status
curl https://icrs-offset-api.fly.dev/health
curl https://icrs-offset-api.fly.dev/api/offsets
```

Replace `icrs-offset-api` with your app name if different.

## Step 6 — Connect the static site

Edit `index.html` in the **repo root**:

```html
<meta name="icrs-offset-api" content="https://icrs-offset-api.fly.dev/api/offsets" />
```

Commit and push to GitHub. GitHub Pages redeploys the site; the Emissions tab will call your Fly API.

## Step 7 — Verify end-to-end

1. Open https://orlando-code.github.io/explore-icrs-2026/ (or your Pages URL)
2. Go to **Emissions**
3. Search your name → **I've offset my travel**
4. Refresh — the green bar and percentage should update
5. Open the site in a private window — same totals (proves it’s not just your browser)

## Staying free

Fly’s free tier (check [fly.io/docs/about/pricing](https://fly.io/docs/about/pricing) for current limits) typically includes:

- Small shared VMs (enough for this API)
- Up to 3 GB of volume storage (this app uses 1 GB)

This API is tiny (SQLite, low traffic). A conference pledge tracker should stay within free limits.

To avoid surprise charges:

```bash
flyctl dashboard
```

Review usage occasionally. Set a billing alert in Fly if offered.

## Useful commands

```bash
flyctl logs              # live logs
flyctl ssh console       # shell on the machine
flyctl deploy            # redeploy after code changes
flyctl apps list
```

## If something fails

**CORS / “registration failed”:** ensure `ALLOWED_ORIGINS` in `fly.toml` includes your exact GitHub Pages URL (no trailing slash). Redeploy after editing.

**Volume not mounted:** `flyctl volumes list` — volume region must match app region (`syd`).

**Wrong CLI:** errors mention “pipelines” or “workers” → you ran Concourse’s `fly`, not `flyctl`.

## Alternatives (also free, more work)

| Option | Effort | Persistence |
|--------|--------|-------------|
| **Fly.io + flyctl** (above) | Low | Yes (volume) |
| Oracle Cloud “Always Free” VM + `docker compose` | High | Yes |
| Railway | Low | Yes, but free credit often runs out |
