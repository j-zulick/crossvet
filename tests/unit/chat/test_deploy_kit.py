"""The hosting kit routes every MCP and sign-in path to the MCP server, and keeps keys out of the repository."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml")  # not in the light install

KIT = Path(__file__).resolve().parents[3] / "deploy" / "chat"


def test_caddy_sends_every_sign_in_path_to_the_mcp_server():
    caddy = (KIT / "Caddyfile").read_text()
    matcher = re.search(r"@mcp path (.+)", caddy).group(1).split()
    for path in ("/mcp", "/authorize", "/token", "/register", "/revoke", "/login", "/.well-known/*"):
        assert path in matcher, path
    assert "reverse_proxy mcp:8788" in caddy and "reverse_proxy api:8787" in caddy


def test_compose_runs_both_servers_signed_in_and_behind_caddy():
    compose = yaml.safe_load((KIT / "compose.yaml").read_text())
    services = compose["services"]
    assert services["api"]["command"][:3] == ["crossvet", "chat", "serve"] and "0.0.0.0" in services["api"]["command"]
    mcp = services["mcp"]["command"]
    assert "--public-url" in mcp and mcp[mcp.index("--public-url") + 1].startswith("https://")
    assert services["caddy"]["ports"] == ["80:80", "443:443"]
    assert not any("ports" in services[name] for name in ("api", "mcp"))  # only Caddy is reachable from outside


def test_the_example_env_has_no_values_but_the_domain_slot():
    for line in (KIT / ".env.example").read_text().splitlines():
        if line and not line.startswith("#"):
            name, _, value = line.partition("=")
            assert value == "", name
