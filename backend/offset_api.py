#!/usr/bin/env python3
"""Minimal offset-registration API for the ICRS emissions tracker.

Stdlib only: SQLite persistence, CORS, rate limiting, Turnstile verification.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import hmac
import json
import os
import re
import secrets
import sqlite3
import threading
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

ATTENDEE_ID_RE = re.compile(r"^offset-[0-9a-f]{8}$")
DELEGATE_ID_RE = re.compile(r"^\d{5}$")
CONTROL_CHARS_RE = re.compile(r"[\x00-\x1f\x7f-\x9f]")
WHITESPACE_RE = re.compile(r"\s+")

MAX_BODY_BYTES = 4096
MAX_NAME_LENGTH = 120
MAX_BUCKET_KEY_LENGTH = 160

# Aggregation buckets. "speakers" are also part of the wider delegate pool, so
# the site sums both when the non-speaker toggle is on.
POOLS = ("speakers", "delegates")
STATUS_PUBLISHED = "published"
STATUS_PENDING = "pending"
STATUS_REVOKED = "revoked"

# Above this many registrations in an hour, new rows are held for review
# instead of published. Normal traffic is a trickle, so a spike is either a
# conference-wide announcement or someone scripting it.
REVIEW_THRESHOLD_PER_HOUR = 60

POST_LIMIT_PER_HOUR = 40
CONTACT_LIMIT_PER_HOUR = 30
# Ceilings across all callers, so a rotating pool of addresses cannot turn the
# per-caller limits into an unlimited budget.
OFFSET_GLOBAL_LIMIT_PER_HOUR = 600
CONTACT_GLOBAL_LIMIT_PER_HOUR = 400
# Bounds the memory a request flood can make the rate limiter allocate.
MAX_RATE_LIMIT_KEYS = 4096

TURNSTILE_VERIFY_URL = "https://challenges.cloudflare.com/turnstile/v0/siteverify"
TURNSTILE_TIMEOUT_SECONDS = 5
# Caps how long a slow or stalled client can hold a worker thread.
REQUEST_TIMEOUT_SECONDS = 20

_db_lock = threading.Lock()
_rate_lock = threading.Lock()
_contacts_lock = threading.Lock()

_rate_windows: dict[str, dict[str, list[float]]] = {}
_global_windows: dict[str, list[float]] = {}
_contacts_cache: tuple[str, float, int, dict[str, str]] | None = None
_delegate_ids_lock = threading.Lock()
_delegate_ids_by_name: dict[str, str] | None = None
_delegate_ids_loaded_path: str | None = None
# Only used when CLIENT_HINT_SALT is unset: hints stay comparable within a
# process lifetime but are not linkable across restarts.
_ephemeral_hint_salt = secrets.token_hex(16)


def _db_path() -> str:
    return os.environ.get("OFFSET_DB_PATH", "data/offsets.db")


def _contacts_path() -> str:
    return os.environ.get("CONTACTS_PATH", "data/contacts.json")


def _delegate_ids_path() -> str:
    return os.environ.get("DELEGATE_IDS_PATH", "data/delegate_ids.csv").strip()


def _require_delegate_id() -> bool:
    return _env_flag("REQUIRE_DELEGATE_ID")


def _env_flag(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name, "").strip().lower()
    if not raw:
        return default
    return raw in ("1", "true", "yes", "on")


def _log(event: str, **fields: Any) -> None:
    payload = {
        "ts": datetime.now(UTC).isoformat(timespec="seconds"),
        "event": event,
        **fields,
    }
    print(json.dumps(payload, ensure_ascii=True), flush=True)


def _client_hint(client_ip: str) -> str:
    """Salted, truncated digest of a caller address.

    Enough to correlate abuse across requests without storing addresses.
    """
    if not client_ip:
        return ""
    salt = os.environ.get("CLIENT_HINT_SALT", "").strip() or _ephemeral_hint_salt
    digest = hashlib.sha256(f"{salt}|{client_ip}".encode()).hexdigest()
    return digest[:16]


def _review_threshold() -> int:
    try:
        return max(0, int(os.environ.get("REVIEW_THRESHOLD_PER_HOUR", REVIEW_THRESHOLD_PER_HOUR)))
    except ValueError:
        return REVIEW_THRESHOLD_PER_HOUR


def _clean_bucket_key(value: Any) -> str:
    """Opaque affiliation bucket label supplied by the site.

    The site computes it with affiliationMapKey(); the server never parses it,
    it only groups by it, so the two cannot drift apart.
    """
    if value is None:
        return ""
    text = CONTROL_CHARS_RE.sub("", str(value))
    text = WHITESPACE_RE.sub(" ", text).strip()
    return text[:MAX_BUCKET_KEY_LENGTH]


def _clean_pool(value: Any) -> str:
    text = str(value or "").strip().lower()
    return text if text in POOLS else "speakers"


def _clean_name(value: Any) -> str | None:
    if value is None:
        return None
    text = unicodedata.normalize("NFC", str(value))
    text = CONTROL_CHARS_RE.sub("", text)
    text = WHITESPACE_RE.sub(" ", text).strip()
    if not text or len(text) > MAX_NAME_LENGTH:
        return None
    if not any(char.isalpha() for char in text):
        return None
    return text


def _delegate_name_key(name: str | None) -> str:
    cleaned = _clean_name(name)
    return cleaned.lower() if cleaned else ""


def _load_delegate_ids() -> dict[str, str]:
    """Map normalized delegate name → 5-digit ID."""
    global _delegate_ids_by_name, _delegate_ids_loaded_path
    path = _delegate_ids_path()
    if not path or not os.path.isfile(path):
        return {}

    with _delegate_ids_lock:
        if _delegate_ids_by_name is not None and _delegate_ids_loaded_path == path:
            return _delegate_ids_by_name

        by_name: dict[str, str] = {}
        try:
            with Path(path).open(encoding="utf-8", newline="") as handle:
                reader = csv.DictReader(handle)
                for row in reader:
                    name = str(row.get("name") or "").strip()
                    delegate_id = str(row.get("delegate_id") or "").strip()
                    if not name or not DELEGATE_ID_RE.fullmatch(delegate_id):
                        continue
                    key = _delegate_name_key(name)
                    if key:
                        by_name[key] = delegate_id
        except OSError:
            by_name = {}

        _delegate_ids_by_name = by_name
        _delegate_ids_loaded_path = path
        return by_name


def _verify_delegate_id(name: str | None, delegate_id: str) -> bool:
    if not _require_delegate_id():
        return True
    if not DELEGATE_ID_RE.fullmatch(delegate_id):
        return False
    index = _load_delegate_ids()
    if not index:
        return False
    key = _delegate_name_key(name)
    if not key:
        return False
    return index.get(key) == delegate_id


def _load_contacts() -> dict[str, str]:
    global _contacts_cache
    path = _contacts_path()
    try:
        stat = os.stat(path)
    except OSError:
        return {}

    with _contacts_lock:
        cached = _contacts_cache
    if cached and cached[0] == path and cached[1] == stat.st_mtime and cached[2] == stat.st_size:
        return cached[3]

    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    raw = payload.get("contacts") if isinstance(payload, dict) else payload
    if not isinstance(raw, dict):
        return {}
    contacts = {
        str(key): str(email).strip()
        for key, email in raw.items()
        if str(email).strip() and "@" in str(email)
    }

    with _contacts_lock:
        _contacts_cache = (path, stat.st_mtime, stat.st_size, contacts)
    return contacts


def _profile_key(name: str, affiliation: str = "") -> str:
    return f"{name.strip()}|{affiliation.strip()}"


def _lookup_contact_email(name: str, affiliation: str = "") -> str | None:
    contacts = _load_contacts()
    if not contacts:
        return None
    clean_name = name.strip()
    clean_affiliation = affiliation.strip()
    if not clean_name:
        return None

    direct = contacts.get(_profile_key(clean_name, clean_affiliation))
    if direct:
        return direct

    prefix = f"{clean_name}|"
    matches = [email for key, email in contacts.items() if key.startswith(prefix)]
    if len(matches) == 1:
        return matches[0]
    return None


def _allowed_origins() -> set[str]:
    raw = os.environ.get(
        "ALLOWED_ORIGINS",
        "https://orlando-codes.com,https://www.orlando-codes.com,https://orlando-code.github.io,http://localhost:8000,http://127.0.0.1:8000",
    )
    return {origin.strip().rstrip("/") for origin in raw.split(",") if origin.strip()}


def _table_columns(conn: sqlite3.Connection, table: str) -> set[str]:
    return {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}


def _init_db() -> None:
    path = _db_path()
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    with _db_lock:
        conn = sqlite3.connect(path)
        try:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS registrations (
                    attendee_id TEXT PRIMARY KEY,
                    name TEXT,
                    created_at TEXT NOT NULL
                )
                """
            )
            existing = _table_columns(conn, "registrations")
            if "source" not in existing:
                conn.execute("ALTER TABLE registrations ADD COLUMN source TEXT")
            if "client_hint" not in existing:
                conn.execute("ALTER TABLE registrations ADD COLUMN client_hint TEXT")
            if "revoked" not in existing:
                conn.execute(
                    "ALTER TABLE registrations ADD COLUMN revoked INTEGER NOT NULL DEFAULT 0"
                )
            if "affiliation_key" not in existing:
                conn.execute("ALTER TABLE registrations ADD COLUMN affiliation_key TEXT")
            if "pool" not in existing:
                conn.execute("ALTER TABLE registrations ADD COLUMN pool TEXT")
            if "status" not in existing:
                conn.execute(
                    "ALTER TABLE registrations ADD COLUMN status TEXT NOT NULL DEFAULT 'published'"
                )
                # Carry over the older boolean so nothing silently reappears.
                conn.execute(
                    "UPDATE registrations SET status = ? WHERE COALESCE(revoked, 0) = 1",
                    (STATUS_REVOKED,),
                )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_registrations_status ON registrations(status)"
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS registration_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    attendee_id TEXT NOT NULL,
                    event TEXT NOT NULL,
                    name TEXT,
                    source TEXT,
                    client_hint TEXT,
                    created_at TEXT NOT NULL
                )
                """
            )
            conn.commit()
        finally:
            conn.close()


def _aggregate_registrations() -> dict[str, Any]:
    """Published totals and per-affiliation counts.

    Deliberately returns no attendee ids: the ids are a hash of a public name,
    so publishing them would publish who has and has not offset.
    """
    counts: dict[str, dict[str, int]] = {pool: {} for pool in POOLS}
    totals: dict[str, int] = {pool: 0 for pool in POOLS}

    with _db_lock:
        conn = sqlite3.connect(_db_path())
        try:
            rows = conn.execute(
                """
                SELECT pool, affiliation_key, COUNT(*) AS tally
                FROM registrations
                WHERE status = ?
                GROUP BY pool, affiliation_key
                """,
                (STATUS_PUBLISHED,),
            ).fetchall()
        finally:
            conn.close()

    for pool, affiliation_key, tally in rows:
        # Rows predating the aggregate schema still count toward the headline;
        # they just cannot shade a location.
        bucket = _clean_pool(pool)
        totals[bucket] += tally
        if affiliation_key:
            counts[bucket][affiliation_key] = counts[bucket].get(affiliation_key, 0) + tally

    return {"counts": counts, "totals": totals}


def _recent_registration_count(window_seconds: int = 3600) -> int:
    cutoff = datetime.fromtimestamp(time.time() - window_seconds, UTC).isoformat(timespec="seconds")
    with _db_lock:
        conn = sqlite3.connect(_db_path())
        try:
            row = conn.execute(
                "SELECT COUNT(*) FROM registrations WHERE created_at >= ?",
                (cutoff,),
            ).fetchone()
        finally:
            conn.close()
    return int(row[0]) if row else 0


def _add_registration(
    attendee_id: str,
    name: str | None,
    *,
    source: str = "api",
    client_hint: str = "",
    affiliation_key: str = "",
    pool: str = "speakers",
    status: str = STATUS_PUBLISHED,
) -> tuple[bool, bool]:
    """Insert a registration, or republish one that was revoked.

    Returns (counts_as_new, reactivated_from_revoked).
    """
    created_at = datetime.now(UTC).isoformat(timespec="seconds")
    with _db_lock:
        conn = sqlite3.connect(_db_path())
        try:
            cursor = conn.execute(
                """
                INSERT OR IGNORE INTO registrations
                    (attendee_id, name, created_at, source, client_hint, revoked,
                     affiliation_key, pool, status)
                VALUES (?, ?, ?, ?, ?, 0, ?, ?, ?)
                """,
                (
                    attendee_id,
                    name,
                    created_at,
                    source,
                    client_hint,
                    affiliation_key,
                    pool,
                    status,
                ),
            )
            if cursor.rowcount == 1:
                conn.execute(
                    """
                    INSERT INTO registration_events
                        (attendee_id, event, name, source, client_hint, created_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        attendee_id,
                        "held" if status == STATUS_PENDING else "created",
                        name,
                        source,
                        client_hint,
                        created_at,
                    ),
                )
                conn.commit()
                return True, False

            row = conn.execute(
                "SELECT status FROM registrations WHERE attendee_id = ?",
                (attendee_id,),
            ).fetchone()
            if not row or row[0] != STATUS_REVOKED:
                conn.execute(
                    """
                    INSERT INTO registration_events
                        (attendee_id, event, name, source, client_hint, created_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (attendee_id, "duplicate", name, source, client_hint, created_at),
                )
                conn.commit()
                return False, False

            conn.execute(
                """
                UPDATE registrations
                SET name = ?, created_at = ?, source = ?, client_hint = ?,
                    affiliation_key = ?, pool = ?, status = ?, revoked = 0
                WHERE attendee_id = ?
                """,
                (
                    name,
                    created_at,
                    source,
                    client_hint,
                    affiliation_key,
                    pool,
                    status,
                    attendee_id,
                ),
            )
            conn.execute(
                """
                INSERT INTO registration_events
                    (attendee_id, event, name, source, client_hint, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    attendee_id,
                    "held" if status == STATUS_PENDING else "republished",
                    name,
                    source,
                    client_hint,
                    created_at,
                ),
            )
            conn.commit()
            return True, True
        finally:
            conn.close()


def _rate_limit_ok(
    client_ip: str,
    *,
    bucket: str,
    limit: int,
    global_limit: int,
) -> tuple[bool, str]:
    """Check per-caller and global hourly budgets, recording the request."""
    now = time.time()
    window_start = now - 3600
    with _rate_lock:
        store = _rate_windows.setdefault(bucket, {})
        for key in [
            key
            for key, stamps in store.items()
            if not stamps or stamps[-1] < window_start
        ]:
            del store[key]

        global_times = [
            stamp for stamp in _global_windows.get(bucket, []) if stamp >= window_start
        ]
        _global_windows[bucket] = global_times
        if len(global_times) >= global_limit:
            return False, "global"

        times = [stamp for stamp in store.get(client_ip, []) if stamp >= window_start]
        if len(times) >= limit:
            store[client_ip] = times
            return False, "caller"
        if client_ip not in store and len(store) >= MAX_RATE_LIMIT_KEYS:
            return False, "capacity"

        times.append(now)
        store[client_ip] = times
        global_times.append(now)
        return True, ""


def _turnstile_secret() -> str:
    return os.environ.get("TURNSTILE_SECRET", "").strip()


def _extract_turnstile_token(payload: dict[str, Any]) -> str:
    for key in ("cf-turnstile-response", "turnstile_token"):
        value = payload.get(key)
        if value:
            return str(value).strip()
    return ""


def _verify_turnstile(token: str, remote_ip: str) -> bool:
    secret = _turnstile_secret()
    if not secret or not token:
        return False

    fields: dict[str, str] = {
        "secret": secret,
        "response": token,
    }
    # Only send remoteip when explicitly enabled — a mismatched proxy IP causes
    # siteverify to reject otherwise valid tokens (common behind Fly.io/CDN).
    if remote_ip and _env_flag("TURNSTILE_SEND_REMOTEIP"):
        fields["remoteip"] = remote_ip

    body = urllib.parse.urlencode(fields).encode("utf-8")
    request = urllib.request.Request(
        TURNSTILE_VERIFY_URL,
        data=body,
        method="POST",
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    try:
        with urllib.request.urlopen(request, timeout=TURNSTILE_TIMEOUT_SECONDS) as response:
            if response.status != 200:
                return False
            result = json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, UnicodeDecodeError):
        return False
    return result.get("success") is True


def _json_response(
    handler: BaseHTTPRequestHandler,
    status: int,
    payload: Any,
    *,
    include_cors: bool = True,
) -> None:
    body = json.dumps(payload, ensure_ascii=True).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    if include_cors:
        handler._send_common_headers()
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


def _wants_html(handler: BaseHTTPRequestHandler) -> bool:
    accept = handler.headers.get("Accept", "")
    return "text/html" in accept.lower() and "application/json" not in accept.split(",")[0].lower()


def _html_response(handler: BaseHTTPRequestHandler, status: int, html: str) -> None:
    body = html.encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "text/html; charset=utf-8")
    handler._send_common_headers()
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


def _offsets_status_html(payload: dict[str, Any]) -> str:
    totals = payload.get("totals") or {}
    published = int(totals.get("speakers") or 0) + int(totals.get("delegates") or 0)
    require_ids = _require_delegate_id()
    delegate_count = len(_load_delegate_ids()) if require_ids else 0
    pretty = json.dumps(payload, ensure_ascii=True, indent=2)
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>ICRS offset API</title>
  <style>
    body {{ font-family: system-ui, sans-serif; max-width: 42rem; margin: 2rem auto; padding: 0 1rem; line-height: 1.5; }}
    h1 {{ font-size: 1.35rem; }}
    .ok {{ color: #2d8a4e; font-weight: 600; }}
    pre {{ background: #f4f6f8; padding: 1rem; border-radius: 8px; overflow: auto; font-size: 0.85rem; }}
    ul {{ padding-left: 1.2rem; }}
  </style>
</head>
<body>
  <h1>ICRS offset API</h1>
  <p class="ok">Running</p>
  <ul>
    <li>Published offsets: <strong>{published}</strong></li>
    <li>Delegate ID required: <strong>{"yes" if require_ids else "no"}</strong></li>
    <li>Delegate IDs loaded: <strong>{delegate_count}</strong></li>
  </ul>
  <p>This is the JSON API used by the emissions page — not the public site.
     Open the site at <code>http://127.0.0.1:8000</code> after
     <code>python3 -m http.server 8000</code>.</p>
  <p>Endpoints: <a href="/health">/health</a> · <a href="/api/offsets?format=json">/api/offsets</a> (JSON)</p>
  <pre>{pretty}</pre>
</body>
</html>"""


class OffsetHandler(BaseHTTPRequestHandler):
    server_version = "ICRSOffsetAPI/1.0"
    timeout = REQUEST_TIMEOUT_SECONDS

    def log_message(self, format: str, *args: Any) -> None:
        return

    def _origin(self) -> str | None:
        origin = self.headers.get("Origin", "").rstrip("/")
        return origin or None

    def _cors_allowed(self) -> bool:
        origin = self._origin()
        if not origin:
            return True
        return origin in _allowed_origins()

    def _send_common_headers(self) -> None:
        origin = self._origin()
        if origin and origin in _allowed_origins():
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Vary", "Origin")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Max-Age", "86400")
        self.send_header("X-Content-Type-Options", "nosniff")

    def _client_ip(self) -> str:
        """Caller address, taken only from a header the proxy itself sets.

        X-Forwarded-For is deliberately ignored: clients can send it, which
        would let anyone pick their own rate-limit bucket. Set
        CLIENT_IP_HEADER to "" when running without a trusted proxy.
        """
        header = os.environ.get("CLIENT_IP_HEADER", "Fly-Client-IP").strip()
        if header:
            value = self.headers.get(header, "").split(",")[0].strip()
            if value:
                return value
        return self.client_address[0]

    def do_OPTIONS(self) -> None:
        if not self._cors_allowed():
            self.send_response(403)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        self.send_response(204)
        self._send_common_headers()
        self.end_headers()

    def do_GET(self) -> None:
        path = urlparse(self.path).path.rstrip("/") or "/"
        if path == "/health":
            _json_response(self, 200, {"ok": True})
            return
        if path == "/api/admin/export":
            self._get_admin_export()
            return
        if path not in {"/", "/api/offsets"}:
            self.send_response(404)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return

        aggregate = _aggregate_registrations()
        payload = {
            "counts": aggregate["counts"],
            "totals": aggregate["totals"],
            "updated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        }
        query = urllib.parse.parse_qs(urlparse(self.path).query)
        if _wants_html(self) and "format" not in query:
            _html_response(self, 200, _offsets_status_html(payload))
            return
        _json_response(self, 200, payload)

    def _get_admin_export(self) -> None:
        expected = os.environ.get("ADMIN_TOKEN", "").strip()
        if not expected:
            # Unconfigured: behave as though the route does not exist.
            self.send_response(404)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return

        header = self.headers.get("Authorization", "")
        supplied = header[7:].strip() if header.lower().startswith("bearer ") else ""
        if not hmac.compare_digest(supplied, expected):
            _log("admin_export_denied", client=_client_hint(self._client_ip()))
            _json_response(self, 403, {"error": "Forbidden."})
            return
        if self._check_rate_limit("admin", 60, 120) is None:
            return

        with _db_lock:
            conn = sqlite3.connect(_db_path())
            conn.row_factory = sqlite3.Row
            try:
                registrations = [
                    dict(row)
                    for row in conn.execute(
                        "SELECT * FROM registrations ORDER BY created_at ASC"
                    )
                ]
                events = [
                    dict(row)
                    for row in conn.execute(
                        "SELECT * FROM registration_events ORDER BY id ASC"
                    )
                ]
            finally:
                conn.close()

        _log("admin_export", registrations=len(registrations), events=len(events))
        _json_response(
            self,
            200,
            {
                "exported_at": datetime.now(UTC).isoformat(timespec="seconds"),
                "registrations": registrations,
                "events": events,
            },
        )

    def do_POST(self) -> None:
        if not self._require_allowed_origin():
            return

        path = urlparse(self.path).path.rstrip("/")
        if path == "/api/offsets":
            self._post_offset()
            return
        if path == "/api/contact":
            self._post_contact()
            return

        self.send_response(404)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def _require_allowed_origin(self) -> bool:
        """Browsers always send Origin on POST, so require it to be one of ours."""
        origin = self._origin()
        if origin and origin in _allowed_origins():
            return True
        if origin is None and not _env_flag("REQUIRE_ORIGIN", True):
            return True
        _json_response(self, 403, {"error": "Origin not allowed."})
        return False

    def _read_json_body(self) -> dict[str, Any] | None:
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except (TypeError, ValueError):
            _json_response(self, 400, {"error": "Invalid request body."})
            return None
        if length <= 0 or length > MAX_BODY_BYTES:
            _json_response(self, 400, {"error": "Invalid request body."})
            return None
        try:
            raw = self.rfile.read(length)
        except (TimeoutError, OSError):
            return None
        if len(raw) != length:
            _json_response(self, 400, {"error": "Invalid request body."})
            return None
        try:
            payload = json.loads(raw.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            _json_response(self, 400, {"error": "Invalid JSON."})
            return None
        if not isinstance(payload, dict):
            _json_response(self, 400, {"error": "Invalid JSON."})
            return None
        return payload

    def _check_rate_limit(self, bucket: str, limit: int, global_limit: int) -> str | None:
        """Returns the caller's hint on success, None after sending a 429."""
        client_ip = self._client_ip()
        allowed, reason = _rate_limit_ok(
            client_ip, bucket=bucket, limit=limit, global_limit=global_limit
        )
        hint = _client_hint(client_ip)
        if allowed:
            return hint
        _log("rate_limited", bucket=bucket, reason=reason, client=hint)
        message = (
            "This service is busy. Try again later."
            if reason != "caller"
            else "Too many requests. Try again later."
        )
        _json_response(self, 429, {"error": message})
        return None

    def _require_turnstile(self, payload: dict[str, Any]) -> bool:
        if _env_flag("SKIP_TURNSTILE_VERIFY"):
            return True
        if not _turnstile_secret():
            _json_response(self, 503, {"error": "Verification is not configured."})
            return False
        turnstile_token = _extract_turnstile_token(payload)
        if not _verify_turnstile(turnstile_token, self._client_ip()):
            _json_response(self, 403, {"error": "Verification failed."})
            return False
        return True

    def _post_offset(self) -> None:
        # Rate limiting runs first so unverified callers cannot make us spend an
        # outbound Turnstile request (and a worker thread) per attempt.
        hint = self._check_rate_limit(
            "offsets", POST_LIMIT_PER_HOUR, OFFSET_GLOBAL_LIMIT_PER_HOUR
        )
        if hint is None:
            return
        payload = self._read_json_body()
        if payload is None:
            return

        attendee_id = str(payload.get("id", "")).strip()
        if not ATTENDEE_ID_RE.fullmatch(attendee_id):
            _json_response(self, 400, {"error": "Invalid attendee id."})
            return
        clean_name = _clean_name(payload.get("name"))
        if payload.get("name") not in (None, "") and clean_name is None:
            _json_response(self, 400, {"error": "Invalid name."})
            return
        affiliation_key = _clean_bucket_key(payload.get("affiliation_key"))
        pool = _clean_pool(payload.get("pool"))
        delegate_id = str(payload.get("delegate_id", "")).strip()

        if _require_delegate_id():
            if not _verify_delegate_id(clean_name, delegate_id):
                _log(
                    "delegate_id_rejected",
                    attendee_id=attendee_id,
                    client=hint,
                )
                _json_response(
                    self,
                    403,
                    {"error": "Delegate ID does not match this name."},
                )
                return

        if not self._require_turnstile(payload):
            return

        threshold = _review_threshold()
        recent = _recent_registration_count()
        held = bool(threshold) and recent >= threshold
        status = STATUS_PENDING if held else STATUS_PUBLISHED

        created, reactivated = _add_registration(
            attendee_id,
            clean_name,
            source="api",
            client_hint=hint,
            affiliation_key=affiliation_key,
            pool=pool,
            status=status,
        )
        accepted = created or reactivated
        if held and accepted:
            _log(
                "registration_held_for_review",
                attendee_id=attendee_id,
                recent_hour=recent,
                threshold=threshold,
                client=hint,
            )
        else:
            _log(
                "offset_registered",
                attendee_id=attendee_id,
                created=created,
                reactivated=reactivated,
                client=hint,
            )
        _json_response(
            self,
            201 if accepted else 200,
            {
                "ok": True,
                "id": attendee_id,
                "created": accepted,
                "reactivated": reactivated,
                # The site thanks the visitor either way; a held row simply is
                # not counted publicly until it has been looked at.
                "pending": held and accepted,
                **(
                    {"delegate_verified": True}
                    if _require_delegate_id()
                    else {}
                ),
            },
        )

    def _post_contact(self) -> None:
        hint = self._check_rate_limit(
            "contact", CONTACT_LIMIT_PER_HOUR, CONTACT_GLOBAL_LIMIT_PER_HOUR
        )
        if hint is None:
            return
        payload = self._read_json_body()
        if payload is None:
            return

        name = _clean_name(payload.get("name"))
        if not name:
            _json_response(self, 400, {"error": "Name is required."})
            return
        affiliation = _clean_name(payload.get("affiliation")) or ""

        if not self._require_turnstile(payload):
            return

        email = _lookup_contact_email(name, affiliation)
        _log("contact_lookup", name=name, found=bool(email), client=hint)
        if not email:
            _json_response(self, 404, {"error": "No verified email available for this person."})
            return

        _json_response(self, 200, {"ok": True, "email": email})


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default=os.environ.get("HOST", "0.0.0.0"))
    parser.add_argument("--port", type=int, default=int(os.environ.get("PORT", "8080")))
    args = parser.parse_args()

    _init_db()
    contacts = _load_contacts()
    server = ThreadingHTTPServer((args.host, args.port), OffsetHandler)
    print(f"Offset API listening on http://{args.host}:{args.port}")
    print(f"Database: {_db_path()}")
    print(f"Contacts: {_contacts_path()} ({len(contacts)} verified emails)")
    print(f"Allowed origins: {', '.join(sorted(_allowed_origins()))}")
    print(f"Client IP header: {os.environ.get('CLIENT_IP_HEADER', 'Fly-Client-IP') or '(socket peer)'}")
    print(f"Hold-for-review above: {_review_threshold()} registrations/hour")
    if _require_delegate_id():
        delegate_ids = _load_delegate_ids()
        print(
            f"Delegate IDs: {_delegate_ids_path()} ({len(delegate_ids)} names, required on POST)"
        )
        if not delegate_ids:
            print("WARNING: REQUIRE_DELEGATE_ID is set but no delegate IDs were loaded.")
    if _env_flag("SKIP_TURNSTILE_VERIFY"):
        print("WARNING: SKIP_TURNSTILE_VERIFY is set — Turnstile is not checked.")
    elif not _turnstile_secret():
        print("WARNING: TURNSTILE_SECRET is unset — POST endpoints will return 503.")
    if not os.environ.get("ADMIN_TOKEN", "").strip():
        print("NOTE: ADMIN_TOKEN is unset — /api/admin/export is disabled (404).")
    server.serve_forever()


if __name__ == "__main__":
    main()
