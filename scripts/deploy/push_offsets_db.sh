#!/usr/bin/env bash
# Push a local SQLite ledger to the Fly volume.
#
# Why not stop the machine + sftp put /data/offsets.db?
#   - fly ssh sftp needs a running VM (fails when the machine is stopped)
#   - fly ssh sftp refuses to overwrite an existing paths
#   - python:3.12-slim has no pkill
#
# Uploads to a temp file, verifies it exists, swaps it in, then restarts so the
# API reopens the new database inode. The previous live file is kept as
# offsets.db.bak (and any prior bak as offsets.db.bak.prev).

set -euo pipefail

APP="${FLY_APP:-icrs-offset-api}"
MACHINE="${FLY_MACHINE:-857677db46d768}"
LOCAL_DB="${1:-./backend/offsets-live.db}"
REMOTE_TMP="/data/offsets-replacement.db"

if [[ ! -f "$LOCAL_DB" ]]; then
  echo "Local database not found: $LOCAL_DB" >&2
  exit 1
fi

echo "Uploading $LOCAL_DB -> $REMOTE_TMP"
flyctl ssh sftp put "$LOCAL_DB" "$REMOTE_TMP" -a "$APP"

echo "Swapping into /data/offsets.db"
flyctl ssh console -a "$APP" -C "python3 -c \"
import os, sys
t = '/data/offsets-replacement.db'
d = '/data/offsets.db'
b = '/data/offsets.db.bak'
if not os.path.exists(t):
    print(f'missing upload: {t}', file=sys.stderr)
    sys.exit(1)
size = os.path.getsize(t)
if size < 1024:
    print(f'upload looks too small ({size} bytes)', file=sys.stderr)
    sys.exit(1)
if os.path.exists(b):
    os.replace(b, b + '.prev')
if os.path.exists(d):
    os.replace(d, b)
os.replace(t, d)
print(f'swapped {size} bytes')
\""

echo "Restarting $MACHINE"
flyctl machine restart "$MACHINE" -a "$APP"

echo "Waiting for health check..."
for _ in $(seq 1 20); do
  if curl -fsS "https://${APP}.fly.dev/health" >/dev/null 2>&1; then
    break
  fi
  sleep 2
done

echo "Live totals:"
curl -sS "https://${APP}.fly.dev/api/offsets"
echo
