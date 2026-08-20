# `scripts/deploy/`

Helpers for the offset-registration API on [Fly.io](https://fly.io/). Require `flyctl` and local secrets.

| Script | Purpose |
|--------|---------|
| `deploy_offset_api.sh` | Build and deploy the offset API. Ensures `backend/data/contacts.json` exists (from template if missing) and `delegate_ids.csv` is present (from `scripts/export_delegate_ids_csv.py`). |
| `push_offsets_db.sh` | Upload a local SQLite ledger to the Fly volume, swap it in as `/data/offsets.db`, and restart the machine. |
| `manage_offset_registrations.py` | Inspect, approve, revoke, and audit offset registrations (`stats`, `list`, `history`, `revoke-matching`, …). See `backend/README.md` and `docs/OFFSETS-FLY-OPS.md`. |

**Local-only inputs (never commit):** `backend/data/contacts.json`, `backend/data/delegate_ids.csv`, `backend/offsets-live.db`.
