#!/usr/bin/env python3
"""Minimal offset-registration API for the ICRS emissions tracker.

Stdlib only: SQLite persistence, CORS, light rate limiting.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

ATTENDEE_ID_RE = re.compile(r"^offset-[0-9a-f]{8}$")
MAX_BODY_BYTES = 4096
POST_LIMIT_PER_HOUR = 40
CONTACT_LIMIT_PER_HOUR = 30
TURNSTILE_VERIFY_URL = "https://challenges.cloudflare.com/turnstile/v0/siteverify"

_db_lock = threading.Lock()
_rate_lock = threading.Lock()
_post_times: dict[str, list[float]] = {}
_contact_times: dict[str, list[float]] = {}


def _db_path() -> str:
    return os.environ.get("OFFSET_DB_PATH", "data/offsets.db")


def _contacts_path() -> str:
    return os.environ.get("CONTACTS_PATH", "data/contacts.json")


def _load_contacts() -> dict[str, str]:
    path = _contacts_path()
    if not os.path.isfile(path):
        return {}
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    contacts = payload.get("contacts") if isinstance(payload, dict) else payload
    if not isinstance(contacts, dict):
        return {}
    return {
        str(key): str(email).strip()
        for key, email in contacts.items()
        if str(email).strip() and "@" in str(email)
    }


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
            conn.commit()
        finally:
            conn.close()


def _list_registrations() -> list[dict[str, str]]:
    with _db_lock:
        conn = sqlite3.connect(_db_path())
        conn.row_factory = sqlite3.Row
        try:
            rows = conn.execute(
                """
                SELECT attendee_id, name, created_at
                FROM registrations
                ORDER BY created_at ASC
                """
            ).fetchall()
            return [dict(row) for row in rows]
        finally:
            conn.close()


def _add_registration(attendee_id: str, name: str | None) -> bool:
    created_at = datetime.now(UTC).isoformat(timespec="seconds")
    with _db_lock:
        conn = sqlite3.connect(_db_path())
        try:
            cursor = conn.execute(
                """
                INSERT OR IGNORE INTO registrations (attendee_id, name, created_at)
                VALUES (?, ?, ?)
                """,
                (attendee_id, name, created_at),
            )
            conn.commit()
            return cursor.rowcount == 1
        finally:
            conn.close()


def _rate_limit_ok(client_ip: str, *, bucket: str = "offsets", limit: int = POST_LIMIT_PER_HOUR) -> bool:
    now = time.time()
    window_start = now - 3600
    store = _post_times if bucket == "offsets" else _contact_times
    with _rate_lock:
        times = [stamp for stamp in store.get(client_ip, []) if stamp >= window_start]
        if len(times) >= limit:
            store[client_ip] = times
            return False
        times.append(now)
        store[client_ip] = times
        return True


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

    body = urllib.parse.urlencode(
        {
            "secret": secret,
            "response": token,
            "remoteip": remote_ip,
        }
    ).encode("utf-8")
    request = urllib.request.Request(
        TURNSTILE_VERIFY_URL,
        data=body,
        method="POST",
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
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
        handler._send_cors()
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


class OffsetHandler(BaseHTTPRequestHandler):
    server_version = "ICRSOffsetAPI/1.0"

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

    def _send_cors(self) -> None:
        origin = self._origin()
        if origin and origin in _allowed_origins():
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Vary", "Origin")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Max-Age", "86400")

    def _client_ip(self) -> str:
        forwarded = self.headers.get("X-Forwarded-For", "")
        if forwarded:
            return forwarded.split(",")[0].strip()
        return self.client_address[0]

    def do_OPTIONS(self) -> None:
        if not self._cors_allowed():
            self.send_response(403)
            self.end_headers()
            return
        self.send_response(204)
        self._send_cors()
        self.end_headers()

    def do_GET(self) -> None:
        if not self._cors_allowed():
            self.send_response(403)
            self.end_headers()
            return

        path = urlparse(self.path).path.rstrip("/") or "/"
        if path not in {"/", "/api/offsets", "/health"}:
            self.send_response(404)
            self.end_headers()
            return

        if path == "/health":
            body = json.dumps({"ok": True}).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self._send_cors()
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return

        rows = _list_registrations()
        payload = {
            "registrations": [row["attendee_id"] for row in rows],
            "count": len(rows),
            "updated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        }
        body = json.dumps(payload, ensure_ascii=True).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self._send_cors()
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self) -> None:
        if not self._cors_allowed():
            self.send_response(403)
            self.end_headers()
            return

        path = urlparse(self.path).path.rstrip("/")
        if path == "/api/offsets":
            self._post_offset()
            return
        if path == "/api/contact":
            self._post_contact()
            return

        self.send_response(404)
        self.end_headers()

    def _read_json_body(self) -> dict[str, Any] | None:
        length = int(self.headers.get("Content-Length", "0"))
        if length <= 0 or length > MAX_BODY_BYTES:
            _json_response(self, 400, {"error": "Invalid request body."})
            return None
        try:
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            _json_response(self, 400, {"error": "Invalid JSON."})
            return None
        if not isinstance(payload, dict):
            _json_response(self, 400, {"error": "Invalid JSON."})
            return None
        return payload

    def _require_turnstile(self, payload: dict[str, Any]) -> bool:
        if not _turnstile_secret():
            _json_response(self, 503, {"error": "Verification is not configured."})
            return False
        turnstile_token = _extract_turnstile_token(payload)
        if not _verify_turnstile(turnstile_token, self._client_ip()):
            _json_response(self, 403, {"error": "Verification failed."})
            return False
        return True

    def _post_offset(self) -> None:
        payload = self._read_json_body()
        if payload is None:
            return
        if not self._require_turnstile(payload):
            return
        if not _rate_limit_ok(self._client_ip(), bucket="offsets", limit=POST_LIMIT_PER_HOUR):
            _json_response(self, 429, {"error": "Too many registrations. Try again later."})
            return

        attendee_id = str(payload.get("id", "")).strip()
        name = payload.get("name")
        clean_name = str(name).strip()[:160] if name else None

        if not ATTENDEE_ID_RE.fullmatch(attendee_id):
            _json_response(self, 400, {"error": "Invalid attendee id."})
            return

        created = _add_registration(attendee_id, clean_name)
        status = 201 if created else 200
        _json_response(
            self,
            status,
            {
                "ok": True,
                "id": attendee_id,
                "created": created,
            },
        )

    def _post_contact(self) -> None:
        payload = self._read_json_body()
        if payload is None:
            return
        if not self._require_turnstile(payload):
            return
        if not _rate_limit_ok(self._client_ip(), bucket="contact", limit=CONTACT_LIMIT_PER_HOUR):
            _json_response(self, 429, {"error": "Too many requests. Try again later."})
            return

        name = str(payload.get("name", "")).strip()
        affiliation = str(payload.get("affiliation", "")).strip()
        if not name:
            _json_response(self, 400, {"error": "Name is required."})
            return

        email = _lookup_contact_email(name, affiliation)
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
    server.serve_forever()


if __name__ == "__main__":
    main()
