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
APP="${FLY_APP:-icrs-offset-api}"

mkdir -p "$BACKEND/data"
if [[ ! -f "$CONTACTS" ]]; then
  echo "No $CONTACTS — using empty template (email reveal will be unavailable)."
  cp "$TEMPLATE" "$CONTACTS"
fi

cd "$BACKEND"
flyctl deploy -a "$APP"
