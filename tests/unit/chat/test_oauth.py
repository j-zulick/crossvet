"""Sign-in for the hosted MCP server: the whole OAuth flow a ChatGPT or claude.ai connector goes through."""

from __future__ import annotations

import base64
import hashlib
import secrets
from urllib.parse import parse_qs, urlsplit

import pytest
from starlette.testclient import TestClient

from open_deep_research.chat import mcp_server
from open_deep_research.chat.oauth import MAX_FAILURES, OwnerOAuth

PUBLIC = "http://localhost"
PASSPHRASE = "correct horse battery staple"
CALLBACK = "http://localhost:9999/callback"


@pytest.fixture
def app(hub):
    provider = OwnerOAuth(PUBLIC, PASSPHRASE, path=":memory:")
    server = mcp_server.build_server(hub, public_url=PUBLIC, oauth=provider)
    with TestClient(server.streamable_http_app(), base_url=PUBLIC, follow_redirects=False) as client:
        client.provider = provider  # type: ignore[attr-defined]
        yield client


def register(client) -> str:
    reply = client.post("/register", json={"redirect_uris": [CALLBACK], "client_name": "Test app", "scope": "crossvet",
                                           "token_endpoint_auth_method": "none", "response_types": ["code"],
                                           "grant_types": ["authorization_code", "refresh_token"]})
    assert reply.status_code == 201, reply.text
    return reply.json()["client_id"]


def start(client, client_id: str, resource: bool = True) -> tuple[str, str]:
    verifier = secrets.token_urlsafe(48)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    reply = client.get("/authorize", params={"response_type": "code", "client_id": client_id, "redirect_uri": CALLBACK,
                                             "code_challenge": challenge, "code_challenge_method": "S256", "state": "s-1",
                                             "scope": "crossvet", **({"resource": f"{PUBLIC}/mcp"} if resource else {})})
    assert reply.status_code == 302, reply.text
    login = reply.headers["location"]
    assert login.startswith(f"{PUBLIC}/login?request=")
    return parse_qs(urlsplit(login).query)["request"][0], verifier


def signed_in(client, resource: bool = True) -> tuple[str, dict]:
    client_id = register(client)
    request_id, verifier = start(client, client_id, resource)
    page = client.get("/login", params={"request": request_id})
    assert page.status_code == 200 and "Test app" in page.text and "localhost:9999" in page.text
    assert page.headers["x-frame-options"] == "DENY"
    reply = client.post("/login", data={"request": request_id, "passphrase": PASSPHRASE})
    assert reply.status_code == 302
    back = urlsplit(reply.headers["location"])
    assert f"{back.scheme}://{back.netloc}{back.path}" == CALLBACK and parse_qs(back.query)["state"] == ["s-1"]
    code = parse_qs(back.query)["code"][0]
    tokens = client.post("/token", data={"grant_type": "authorization_code", "code": code, "redirect_uri": CALLBACK,
                                         "client_id": client_id, "code_verifier": verifier})
    assert tokens.status_code == 200, tokens.text
    again = client.post("/token", data={"grant_type": "authorization_code", "code": code, "redirect_uri": CALLBACK,
                                        "client_id": client_id, "code_verifier": verifier})
    assert again.status_code == 400  # a code works once
    return client_id, tokens.json()


def mcp_call(client, token: str | None):
    headers = {"accept": "application/json, text/event-stream", "content-type": "application/json"}
    if token:
        headers["authorization"] = f"Bearer {token}"
    body = {"jsonrpc": "2.0", "id": 1, "method": "initialize",
            "params": {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "test", "version": "1"}}}
    return client.post("/mcp", json=body, headers=headers)


def test_metadata_names_the_endpoints(app):
    meta = app.get("/.well-known/oauth-authorization-server").json()
    assert meta["authorization_endpoint"] == f"{PUBLIC}/authorize" and meta["registration_endpoint"] == f"{PUBLIC}/register"
    assert "S256" in meta["code_challenge_methods_supported"]


def test_mcp_needs_a_token(app):
    reply = mcp_call(app, None)
    assert reply.status_code == 401 and "resource_metadata" in reply.headers.get("www-authenticate", "")


def test_full_sign_in_then_the_tools_answer(app):
    _, tokens = signed_in(app)
    assert tokens["token_type"].lower() == "bearer" and tokens["expires_in"] == 3600 and tokens["refresh_token"]
    reply = mcp_call(app, tokens["access_token"])
    assert reply.status_code == 200 and "crossvet-chat" in reply.text


def test_apps_that_do_not_name_the_server_still_get_a_working_token(app):
    _, tokens = signed_in(app, resource=False)
    assert mcp_call(app, tokens["access_token"]).status_code == 200


def test_refresh_replaces_the_pair(app):
    client_id, tokens = signed_in(app)
    fresh = app.post("/token", data={"grant_type": "refresh_token", "refresh_token": tokens["refresh_token"],
                                     "client_id": client_id})
    assert fresh.status_code == 200, fresh.text
    assert mcp_call(app, tokens["access_token"]).status_code == 401  # the old access token stopped working
    assert mcp_call(app, fresh.json()["access_token"]).status_code == 200
    reused = app.post("/token", data={"grant_type": "refresh_token", "refresh_token": tokens["refresh_token"],
                                      "client_id": client_id})
    assert reused.status_code == 400


def test_wrong_passphrase_then_lockout(app):
    client_id = register(app)
    request_id, _ = start(app, client_id)
    wrong = app.post("/login", data={"request": request_id, "passphrase": "guess"})
    assert wrong.status_code == 401 and "wrong passphrase" in wrong.text
    for _ in range(MAX_FAILURES - 1):
        app.post("/login", data={"request": request_id, "passphrase": "guess"})
    locked = app.post("/login", data={"request": request_id, "passphrase": PASSPHRASE})
    assert locked.status_code == 429 and "15 minutes" in locked.text


def test_unknown_or_expired_requests_are_refused(app):
    page = app.get("/login", params={"request": "made-up"})
    assert page.status_code == 400 and "expired or is unknown" in page.text


def test_only_hashes_are_stored(app):
    _, tokens = signed_in(app)
    stored = " ".join(str(row) for row in app.provider.db.execute("SELECT * FROM tokens"))  # type: ignore[attr-defined]
    assert tokens["access_token"] not in stored and tokens["refresh_token"] not in stored


def test_requests_for_another_host_are_refused_even_with_a_token(app):
    _, tokens = signed_in(app)
    reply = app.post("/mcp", json={}, headers={"host": "evil.example", "accept": "application/json, text/event-stream",
                                               "content-type": "application/json",
                                               "authorization": f"Bearer {tokens['access_token']}"})
    assert reply.status_code in (400, 421)


def test_a_short_passphrase_is_refused():
    with pytest.raises(ValueError, match="at least 16"):
        OwnerOAuth(PUBLIC, "short", path=":memory:")


def test_main_refuses_unsafe_setups(monkeypatch, capsys):
    monkeypatch.delenv("CROSSVET_CHAT_TOKEN", raising=False)
    monkeypatch.delenv("CROSSVET_CHAT_PUBLIC_URL", raising=False)
    assert mcp_server.main(http=True, host="0.0.0.0") == 2
    assert "only listens on localhost" in capsys.readouterr().err
    assert mcp_server.main(http=True, host="0.0.0.0", public_url="https://chat.example.com") == 2
    assert "CROSSVET_CHAT_TOKEN" in capsys.readouterr().err
    monkeypatch.setenv("CROSSVET_CHAT_TOKEN", PASSPHRASE)
    assert mcp_server.main(http=True, host="0.0.0.0", public_url="http://chat.example.com") == 2
    assert "https://" in capsys.readouterr().err
