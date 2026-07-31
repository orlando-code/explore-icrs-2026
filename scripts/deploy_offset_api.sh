#!/usr/bin/env bash
# Build and deploy the offset API to Fly.
#
# contacts.json is gitignored (verified emails). This copies the empty template
# when you have not run export_contact_api_data.py locally first.

set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
BACKEND="$ROOT/backend"
CONTACTS="$BACKEND/data/contacts.json"
TEMPLATE="$BACKEND/data/contacts.template.json"
DELEGATE_CSV="$BACKEND/data/delegate_ids.csv"
DELEGATE_SAMPLE="$BACKEND/data/delegate_ids.sample.csv"
APP="${FLY_APP:-icrs-offset-api}"

mkdir -p "$BACKEND/data"
if [[ ! -f "$CONTACTS" ]]; then
  echo "No $CONTACTS — using empty template (email reveal will be unavailable)."
  cp "$TEMPLATE" "$CONTACTS"
fi
if [[ ! -f "$DELEGATE_CSV" ]]; then
  if [[ -f "$DELEGATE_SAMPLE" ]]; then
    echo "No $DELEGATE_CSV — using sample delegate list (local testing only)."
    cp "$DELEGATE_SAMPLE" "$DELEGATE_CSV"
  else
    echo "Missing delegate ID list: $DELEGATE_CSV" >&2
    exit 1
  fi
fi

cd "$BACKEND"
flyctl deploy -a "$APP"
