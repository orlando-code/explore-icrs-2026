# ICRS API proxy (Cloudflare Worker)

Chrome on iOS can fail cross-origin `fetch()` to `*.fly.dev` even after Turnstile
succeeds (the browser reports a generic network error). This Worker serves:

- `https://orlando-codes.com/explore-icrs-2026/api/contact`
- `https://orlando-codes.com/explore-icrs-2026/api/offsets`

and forwards to the Fly.io API so the browser stays on the first-party origin.

The static site already tries these same-origin URLs first (see `js/config.js`).

## Deploy the script

```bash
npx wrangler deploy --config cloudflare/wrangler.toml
```

## Attach the route (required)

`orlando-codes.com` must be a zone on the **same** Cloudflare account you deploy
from. In the dashboard:

1. Workers & Pages → **icrs-api-proxy** → Triggers
2. Add route: `orlando-codes.com/explore-icrs-2026/api/*` (zone: orlando-codes.com)
3. Add route: `www.orlando-codes.com/explore-icrs-2026/api/*` if you use www

Confirm (should be `204`, not a GitHub Pages HTML 404):

```bash
curl -sS -D - -o /dev/null -X OPTIONS \
  'https://orlando-codes.com/explore-icrs-2026/api/contact' \
  -H 'Origin: https://orlando-codes.com' \
  -H 'Access-Control-Request-Method: POST' | head
```
