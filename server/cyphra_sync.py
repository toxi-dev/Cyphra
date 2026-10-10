#!/usr/bin/env python3
"""Cyphra's optional opaque encrypted sync store. Python stdlib; MPL-2.0.

Bind only on loopback behind an administrator-managed HTTPS reverse proxy.
No browser passwords, bookmarks, URLs, keys or preference plaintext enter this
service. It can still see client connection metadata and ciphertext sizes.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import hmac
import json
import os
from pathlib import Path
import re
import secrets
import sqlite3
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit

MAX_CIPHERTEXT = 2 * 1024 * 1024
MAX_BODY = MAX_CIPHERTEXT * 4 // 3 + 4096
VAULT = re.compile(r"[a-f0-9]{32}\Z")
TOKEN = re.compile(r"[A-Za-z0-9_-]{43}\Z")


def token_hash(token: str) -> bytes:
    return hashlib.sha256(token.encode("ascii")).digest()


def decode_base64(value: str, limit: int) -> bytes:
    if not isinstance(value, str) or len(value) > limit * 4 // 3 + 4 or not re.fullmatch(r"[A-Za-z0-9_-]+", value):
        raise ValueError("Invalid envelope encoding")
    decoded = base64.b64decode(value + "=" * (-len(value) % 4), altchars=b"-_", validate=True)
    if len(decoded) > limit or base64.urlsafe_b64encode(decoded).decode().rstrip("=") != value:
        raise ValueError("Invalid envelope encoding")
    return decoded


def validate_envelope(envelope: dict) -> str:
    if not isinstance(envelope, dict) or set(envelope) != {"version", "nonce", "ciphertext"} or envelope["version"] != 1:
        raise ValueError("Invalid encrypted envelope")
    if len(decode_base64(envelope["nonce"], 12)) != 12:
        raise ValueError("Invalid envelope nonce")
    if len(decode_base64(envelope["ciphertext"], MAX_CIPHERTEXT)) < 16:
        raise ValueError("Missing authentication tag")
    return json.dumps(envelope, separators=(",", ":"))


class Store:
    def __init__(self, directory: Path, invitation: str):
        if not TOKEN.fullmatch(invitation):
            raise ValueError("Invitation token must be 43 URL-safe characters")
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(directory, 0o700)
        self.database = directory / "vaults.sqlite3"
        self.invite_hash = token_hash(invitation)
        with self.connect() as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.execute("CREATE TABLE IF NOT EXISTS vaults (id TEXT PRIMARY KEY, token_hash BLOB NOT NULL, revision INTEGER NOT NULL, envelope TEXT NOT NULL)")
        os.chmod(self.database, 0o600)

    def connect(self):
        db = sqlite3.connect(self.database, timeout=10)
        db.execute("PRAGMA busy_timeout=10000")
        return db

    def create(self, invitation: str, vault: str, token: str, envelope: dict):
        if not hmac.compare_digest(token_hash(invitation), self.invite_hash):
            raise PermissionError
        if not isinstance(vault, str) or not VAULT.fullmatch(vault) or not isinstance(token, str) or not TOKEN.fullmatch(token):
            raise ValueError("Invalid vault credentials")
        encoded = validate_envelope(envelope)
        with self.connect() as db:
            try:
                db.execute("INSERT INTO vaults VALUES (?, ?, 1, ?)", (vault, token_hash(token), encoded))
            except sqlite3.IntegrityError:
                return None
        return {"revision": 1}

    def get(self, vault: str, token: str):
        with self.connect() as db:
            row = db.execute("SELECT token_hash, revision, envelope FROM vaults WHERE id=?", (vault,)).fetchone()
        # Unknown vaults have the same externally visible response as bad tokens.
        expected = row[0] if row else bytes(32)
        if not hmac.compare_digest(token_hash(token), expected) or row is None:
            raise PermissionError
        return {"revision": row[1], "envelope": json.loads(row[2])}

    def update(self, vault: str, token: str, revision: int, envelope: dict):
        if type(revision) is not int or not 1 <= revision < 2**53 - 1:
            raise ValueError("Invalid revision")
        encoded = validate_envelope(envelope)
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT token_hash, revision FROM vaults WHERE id=?", (vault,)).fetchone()
            expected = row[0] if row else bytes(32)
            if not hmac.compare_digest(token_hash(token), expected) or row is None:
                raise PermissionError
            if row[1] != revision:
                return None
            db.execute("UPDATE vaults SET revision=?, envelope=? WHERE id=? AND revision=?", (revision + 1, encoded, vault, revision))
        return {"revision": revision + 1}


class Handler(BaseHTTPRequestHandler):
    server_version = "CyphraSync"
    sys_version = ""
    protocol_version = "HTTP/1.1"

    def log_message(self, *_):
        # Access logs would create a device/vault activity history. Operational
        # service start/fatal errors are handled by the supervisor instead.
        pass

    def reply(self, status: int, data: dict):
        body = json.dumps(data, separators=(",", ":")).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(body)
        self.close_connection = True

    def authenticate(self):
        # This is a native-browser API, never a website-facing CORS service.
        if self.headers.get("Origin") or self.headers.get("Referer") or self.headers.get("Sec-Fetch-Site") == "cross-site":
            self.reply(403, {"error": "Website requests are not accepted"})
            return None
        match = re.fullmatch(r"Bearer ([A-Za-z0-9_-]{43})", self.headers.get("Authorization", ""))
        if not match:
            self.reply(401, {"error": "Authorization failed"})
            return None
        return match[1]

    def read_body(self):
        content_type = self.headers.get("Content-Type", "").split(";", 1)[0].strip().lower()
        if content_type != "application/json" or self.headers.get("Transfer-Encoding"):
            raise ValueError("Use a bounded JSON request")
        raw_length = self.headers.get("Content-Length", "")
        if not raw_length.isdigit() or not 1 <= int(raw_length) <= MAX_BODY:
            raise ValueError("Request body is missing or too large")
        self.connection.settimeout(15)
        raw = self.rfile.read(int(raw_length))
        if len(raw) != int(raw_length):
            raise ValueError("Incomplete request")
        data = json.loads(raw)
        if not isinstance(data, dict):
            raise ValueError("Expected a JSON object")
        return data

    def dispatch(self, method):
        token = self.authenticate()
        if token is None:
            return
        url = urlsplit(self.path)
        if url.query or url.fragment:
            self.reply(404, {"error": "Unknown endpoint"})
            return
        try:
            if method == "POST" and url.path == "/v1/vaults":
                body = self.read_body()
                if set(body) != {"vault", "token", "envelope"}:
                    raise ValueError("Invalid creation request")
                result = self.server.store.create(token, body["vault"], body["token"], body["envelope"])
                self.reply(201 if result else 409, result or {"error": "Vault already exists"})
                return
            match = re.fullmatch(r"/v1/vaults/([a-f0-9]{32})", url.path)
            if match and method == "GET":
                self.reply(200, self.server.store.get(match[1], token))
            elif match and method == "PUT":
                body = self.read_body()
                if set(body) != {"revision", "envelope"}:
                    raise ValueError("Invalid update request")
                result = self.server.store.update(match[1], token, body["revision"], body["envelope"])
                self.reply(200 if result else 409, result or {"error": "Revision conflict"})
            else:
                self.reply(404, {"error": "Unknown endpoint"})
        except PermissionError:
            self.reply(401, {"error": "Authorization failed"})
        except (ValueError, TypeError, KeyError, UnicodeError):
            self.reply(400, {"error": "Invalid request"})
        except (TimeoutError, OSError):
            self.close_connection = True
        except sqlite3.Error:
            self.reply(503, {"error": "Storage temporarily unavailable"})

    def do_GET(self):
        self.dispatch("GET")

    def do_POST(self):
        self.dispatch("POST")

    def do_PUT(self):
        self.dispatch("PUT")

    def do_OPTIONS(self):
        self.reply(405, {"error": "Website requests are not accepted"})


class Server(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, address, store):
        if address[0] not in {"127.0.0.1", "::1"}:
            raise ValueError("Cyphra Sync must bind on loopback behind HTTPS")
        self.store = store
        super().__init__(address, Handler)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, required=True)
    parser.add_argument("--invite-file", type=Path, required=True)
    parser.add_argument("--port", type=int, default=9087)
    parser.add_argument("--init", action="store_true", help="Create a private invitation file and initialize storage, then exit")
    args = parser.parse_args()
    os.umask(0o077)
    if args.init:
        args.invite_file.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        # Never replace an existing invitation or print it to a build log.
        with args.invite_file.open("x") as stream:
            stream.write(secrets.token_urlsafe(32) + "\n")
        os.chmod(args.invite_file, 0o600)
    invitation = args.invite_file.read_text().strip()
    store = Store(args.data_dir, invitation)
    if not args.init:
        Server(("127.0.0.1", args.port), store).serve_forever(poll_interval=0.5)


if __name__ == "__main__":
    main()
