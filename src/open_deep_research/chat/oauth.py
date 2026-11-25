"""Sign-in for the hosted MCP server, so the ChatGPT and claude.ai apps can connect as you.

One owner. The apps register themselves (OAuth dynamic client registration, which they need),
send you to ``/login``, and you sign in with the passphrase in ``CROSSVET_CHAT_TOKEN``; only then
does the app get a code, which it trades for an access token (1 hour) and a refresh token (30
days, replaced on every use). The MCP SDK serves the OAuth endpoints and checks PKCE, redirect
URIs and scopes; this module stores clients and tokens and checks the passphrase.

Only SHA-256 hashes of codes and tokens are stored, in their own SQLite file
(``CROSSVET_CHAT_OAUTH_DB``, default ``chat-oauth.db`` next to the chat store). Five wrong
passphrases in 15 minutes lock sign-in for the rest of that window.
"""

from __future__ import annotations

import hashlib
import hmac
import html
import json
import os
import secrets
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any

from mcp.server.auth.provider import (
    AccessToken,
    AuthorizationCode,
    AuthorizationParams,
    RefreshToken,
    RegistrationError,
    construct_redirect_uri,
)
from mcp.shared.auth import OAuthClientInformationFull, OAuthToken

CODE_SECONDS = 300
ACCESS_SECONDS = 3600
REFRESH_SECONDS = 30 * 86400
PENDING_SECONDS = 600
MAX_CLIENTS = 100
MAX_FAILURES = 5
LOCK_SECONDS = 900
SIGN_IN_MIN_CHARS = 16
SCOPE = "crossvet"

SCHEMA = """
CREATE TABLE IF NOT EXISTS clients (client_id TEXT PRIMARY KEY, info TEXT NOT NULL, ts REAL NOT NULL);
CREATE TABLE IF NOT EXISTS pending (id TEXT PRIMARY KEY, client_id TEXT NOT NULL, params TEXT NOT NULL, expires REAL NOT NULL);
CREATE TABLE IF NOT EXISTS codes (hash TEXT PRIMARY KEY, data TEXT NOT NULL, expires REAL NOT NULL);
CREATE TABLE IF NOT EXISTS tokens (hash TEXT PRIMARY KEY, kind TEXT NOT NULL, client_id TEXT NOT NULL, scopes TEXT NOT NULL,
  resource TEXT, family TEXT NOT NULL, expires REAL NOT NULL);
CREATE TABLE IF NOT EXISTS failures (ts REAL NOT NULL);
"""


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def default_path() -> str:
    """Where tokens are kept unless ``CROSSVET_CHAT_OAUTH_DB`` says otherwise."""
    from open_deep_research.chat.config import default_db_path

    return os.environ.get("CROSSVET_CHAT_OAUTH_DB") or str(Path(default_db_path()).with_name("chat-oauth.db"))


class OwnerOAuth:
    """An OAuth authorization server for one owner, for the MCP SDK's ``auth_server_provider``."""

    def __init__(self, issuer: str, secret: str, path: str | None = None, clock: Any = time.time) -> None:  # noqa: D107
        if len(secret) < SIGN_IN_MIN_CHARS:
            raise ValueError(f"CROSSVET_CHAT_TOKEN must be at least {SIGN_IN_MIN_CHARS} characters to sign in from the internet")
        self.issuer = issuer.rstrip("/")
        self.resource = f"{self.issuer}/mcp"  # tokens are for this server; apps that don't say which get this one
        self._secret = secret
        self.clock = clock
        path = path or default_path()
        if path != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path, check_same_thread=False, timeout=10)
        self.db.executescript(SCHEMA)
        self._lock = threading.Lock()

    def _run(self, sql: str, params: tuple = ()) -> list[tuple]:
        with self._lock:
            rows = self.db.execute(sql, params).fetchall()
            self.db.commit()
            return rows

    # --- clients ---

    async def get_client(self, client_id: str) -> OAuthClientInformationFull | None:  # noqa: D102
        rows = self._run("SELECT info FROM clients WHERE client_id=?", (client_id,))
        return OAuthClientInformationFull.model_validate_json(rows[0][0]) if rows else None

    async def register_client(self, client_info: OAuthClientInformationFull) -> None:  # noqa: D102
        if self._run("SELECT COUNT(*) FROM clients")[0][0] >= MAX_CLIENTS:
            raise RegistrationError(error="invalid_client_metadata", error_description="too many registered clients")
        self._run("INSERT OR REPLACE INTO clients(client_id, info, ts) VALUES (?,?,?)",
                  (client_info.client_id, client_info.model_dump_json(), self.clock()))

    # --- the sign-in step ---

    async def authorize(self, client: OAuthClientInformationFull, params: AuthorizationParams) -> str:
        """Park the request and send the person to the sign-in page."""
        request_id = secrets.token_urlsafe(24)
        self._run("INSERT INTO pending(id, client_id, params, expires) VALUES (?,?,?,?)",
                  (request_id, client.client_id, params.model_dump_json(), self.clock() + PENDING_SECONDS))
        return f"{self.issuer}/login?request={request_id}"

    def pending(self, request_id: str) -> tuple[OAuthClientInformationFull, AuthorizationParams] | None:
        """Return the parked request, or ``None`` when it is unknown or expired."""
        rows = self._run("SELECT client_id, params, expires FROM pending WHERE id=?", (request_id,))
        if not rows or rows[0][2] < self.clock():
            return None
        info = self._run("SELECT info FROM clients WHERE client_id=?", (rows[0][0],))
        if not info:
            return None
        return OAuthClientInformationFull.model_validate_json(info[0][0]), AuthorizationParams.model_validate_json(rows[0][1])

    def locked(self) -> bool:
        """Whether too many wrong passphrases were tried recently."""
        since = self.clock() - LOCK_SECONDS
        return self._run("SELECT COUNT(*) FROM failures WHERE ts >= ?", (since,))[0][0] >= MAX_FAILURES

    def sign_in(self, request_id: str, passphrase: str) -> str:
        """Check the passphrase; return where to send the browser (the app, with a code). Raise ``PermissionError``."""
        if self.locked():
            raise PermissionError("too many wrong passphrases; try again in 15 minutes")
        if not hmac.compare_digest(passphrase.encode(), self._secret.encode()):
            self._run("INSERT INTO failures(ts) VALUES (?)", (self.clock(),))
            raise PermissionError("wrong passphrase")
        found = self.pending(request_id)
        if found is None:
            raise PermissionError("this sign-in request expired; start again from the app")
        client, params = found
        self._run("DELETE FROM pending WHERE id=?", (request_id,))
        code = secrets.token_urlsafe(32)
        data = AuthorizationCode(code=code, scopes=params.scopes or [SCOPE], expires_at=self.clock() + CODE_SECONDS,
                                 client_id=client.client_id, code_challenge=params.code_challenge,
                                 redirect_uri=params.redirect_uri,
                                 redirect_uri_provided_explicitly=params.redirect_uri_provided_explicitly,
                                 resource=params.resource or self.resource, subject="owner")
        self._run("INSERT INTO codes(hash, data, expires) VALUES (?,?,?)", (_hash(code), data.model_dump_json(), data.expires_at))
        return construct_redirect_uri(str(params.redirect_uri), code=code, state=params.state)

    # --- codes and tokens ---

    async def load_authorization_code(self, client: OAuthClientInformationFull, authorization_code: str) -> AuthorizationCode | None:  # noqa: D102
        rows = self._run("SELECT data, expires FROM codes WHERE hash=?", (_hash(authorization_code),))
        if not rows or rows[0][1] < self.clock():
            return None
        code = AuthorizationCode.model_validate_json(rows[0][0])
        return code if code.client_id == client.client_id else None

    def _issue(self, client_id: str, scopes: list[str], resource: str | None, family: str | None = None) -> OAuthToken:
        family = family or secrets.token_hex(8)
        access, refresh = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
        now = self.clock()
        for token, kind, ttl in ((access, "access", ACCESS_SECONDS), (refresh, "refresh", REFRESH_SECONDS)):
            self._run("INSERT INTO tokens(hash, kind, client_id, scopes, resource, family, expires) VALUES (?,?,?,?,?,?,?)",
                      (_hash(token), kind, client_id, json.dumps(scopes), resource, family, now + ttl))
        return OAuthToken(access_token=access, token_type="Bearer", expires_in=ACCESS_SECONDS, scope=" ".join(scopes),
                          refresh_token=refresh)

    async def exchange_authorization_code(self, client: OAuthClientInformationFull, authorization_code: AuthorizationCode) -> OAuthToken:  # noqa: D102
        gone = self._run("DELETE FROM codes WHERE hash=? RETURNING hash", (_hash(authorization_code.code),))
        if not gone:  # a code works once
            from mcp.server.auth.provider import TokenError

            raise TokenError(error="invalid_grant", error_description="the code was already used")
        return self._issue(client.client_id, authorization_code.scopes, authorization_code.resource)

    def _token(self, token: str, kind: str) -> tuple | None:
        rows = self._run("SELECT client_id, scopes, resource, family, expires FROM tokens WHERE hash=? AND kind=?",
                         (_hash(token), kind))
        if not rows or rows[0][4] < self.clock():
            return None
        return rows[0]

    async def load_refresh_token(self, client: OAuthClientInformationFull, refresh_token: str) -> RefreshToken | None:  # noqa: D102
        row = self._token(refresh_token, "refresh")
        if row is None or row[0] != client.client_id:
            return None
        return RefreshToken(token=refresh_token, client_id=row[0], scopes=json.loads(row[1]), expires_at=int(row[4]),
                            resource=row[2], subject="owner")

    async def exchange_refresh_token(self, client: OAuthClientInformationFull, refresh_token: RefreshToken,
                                     scopes: list[str]) -> OAuthToken:
        """Replace the whole token pair: the old refresh token and its access token stop working."""
        row = self._token(refresh_token.token, "refresh")
        family = row[3] if row else None
        if family:
            self._run("DELETE FROM tokens WHERE family=?", (family,))
        return self._issue(client.client_id, scopes or refresh_token.scopes, refresh_token.resource)

    async def load_access_token(self, token: str) -> AccessToken | None:  # noqa: D102
        row = self._token(token, "access")
        if row is None:
            return None
        return AccessToken(token=token, client_id=row[0], scopes=json.loads(row[1]), expires_at=int(row[4]), resource=row[2],
                           subject="owner")

    async def revoke_token(self, token: AccessToken | RefreshToken) -> None:
        """Revoke the token and the other token of its pair."""
        rows = self._run("SELECT family FROM tokens WHERE hash=?", (_hash(token.token),))
        if rows:
            self._run("DELETE FROM tokens WHERE family=?", (rows[0][0],))


PAGE = """<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width">
<title>Sign in: Crossvet chat</title><style>
body{{font:16px/1.5 system-ui,sans-serif;max-width:26rem;margin:4rem auto;padding:0 1rem;color:#1d1d1f}}
input{{font:inherit;width:100%;padding:.5rem;margin:.5rem 0;box-sizing:border-box}}
button{{font:inherit;padding:.5rem 1rem}}.error{{color:#b00020}}small{{color:#555}}</style></head><body>
<h1>Crossvet chat</h1>
<p><strong>{client}</strong> wants to use your Crossvet chat: ask your models, read and write your shared notes, and rate answers.</p>
<p><small>After you sign in, it is sent back to {target}.</small></p>
{error}
<form method="post" action="/login"><input type="hidden" name="request" value="{request}">
<label>Passphrase (<code>CROSSVET_CHAT_TOKEN</code>)<input type="password" name="passphrase" autocomplete="current-password" autofocus required></label>
<button type="submit">Sign in</button></form></body></html>"""

HEADERS = {"Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'; form-action 'self'",
           "X-Frame-Options": "DENY", "Cache-Control": "no-store", "Referrer-Policy": "no-referrer"}


def login_page(provider: OwnerOAuth, request_id: str, error: str = "") -> tuple[int, str]:
    """Return the sign-in page for a parked request (status, HTML)."""
    from urllib.parse import urlsplit

    found = provider.pending(request_id)
    if found is None:
        return 400, PAGE.format(client="This app", target="the app", request="",
                                error='<p class="error">This sign-in request expired or is unknown. Start again from the app.</p>')
    client, params = found
    target = urlsplit(str(params.redirect_uri)).netloc or "the app"
    return 200, PAGE.format(client=html.escape(client.client_name or "An app"), target=html.escape(target),
                            request=html.escape(request_id), error=f'<p class="error">{html.escape(error)}</p>' if error else "")


def add_login_routes(server: Any, provider: OwnerOAuth) -> None:
    """Add ``GET`` and ``POST /login`` to a FastMCP server."""
    import asyncio

    from starlette.requests import Request
    from starlette.responses import HTMLResponse, RedirectResponse, Response

    @server.custom_route("/login", methods=["GET"])
    async def login_form(request: Request) -> Response:
        status, page = login_page(provider, request.query_params.get("request", ""))
        return HTMLResponse(page, status_code=status, headers=HEADERS)

    @server.custom_route("/login", methods=["POST"])
    async def login_submit(request: Request) -> Response:
        form = await request.form()
        request_id, passphrase = str(form.get("request", "")), str(form.get("passphrase", ""))
        try:
            target = provider.sign_in(request_id, passphrase)
        except PermissionError as exc:
            await asyncio.sleep(1)  # slows guessing
            status, page = login_page(provider, request_id, str(exc))
            return HTMLResponse(page, status_code=429 if provider.locked() else 401 if status == 200 else status,
                                headers=HEADERS)
        return RedirectResponse(target, status_code=302, headers={"Cache-Control": "no-store"})
