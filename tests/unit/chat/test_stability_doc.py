"""docs/STABILITY.md lists the public interfaces; each list must match the code."""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

from crossvet.chat import cli, mcp_server
from crossvet.chat.server import create_app

ROOT = Path(__file__).resolve().parents[3]
DOC = (ROOT / "docs" / "STABILITY.md").read_text()


def listed(name: str) -> set[str]:
    block = re.search(rf"<!-- list:{name} -->(.*?)<!-- /list -->", DOC, re.S)
    assert block, name
    return set(re.findall(r"`([^`]+)`", block.group(1)))


def test_console_scripts():
    scripts = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]["scripts"]
    assert listed("scripts") == set(scripts)


def test_chat_subcommands():
    parser = cli.build_parser()
    sub = next(a for a in parser._actions if a.__class__.__name__ == "_SubParsersAction")
    assert listed("chat-commands") == set(sub.choices)


def test_http_paths(hub):
    assert listed("http") == {route.path for route in create_app(hub, token="").routes}


def test_mcp_tools(hub):
    assert listed("mcp-tools") == set(mcp_server.tools(hub))
