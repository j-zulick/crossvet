"""docs/STABILITY.md lists exactly what the code offers."""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

from crossvet import cli, mcp_server, server
from crossvet.config import LIMIT_KEYS, TOP_KEYS

ROOT = Path(__file__).resolve().parents[2]
DOC = (ROOT / "docs" / "STABILITY.md").read_text()


def listed(name: str) -> set[str]:
    block = re.search(rf"<!-- list:{name} -->\n(.*?)\n<!-- /list -->", DOC, re.S)
    assert block, name
    return set(re.findall(r"`([^`]+)`", block.group(1)))


def test_commands():
    sub = next(a for a in cli.build_parser()._actions if a.dest == "command")
    assert listed("commands") == set(sub.choices)


def test_http_paths(cv):
    assert listed("http") == {r.path for r in server.create_app(cv, token="").routes}


def test_mcp_tools(cv):
    assert listed("mcp-tools") == set(mcp_server.tools(cv))


def test_example_settings_use_every_key_and_parse():
    from crossvet.config import parse

    data = tomllib.loads((ROOT / "crossvet.example.toml").read_text())
    assert set(data) | {"prices", "store"} == TOP_KEYS
    assert set(data["limits"]) == LIMIT_KEYS
    parse(data, "example")


def test_env_example_lists_every_variable_the_code_reads():
    env = (ROOT / ".env.example").read_text()
    code = "".join(p.read_text() for p in (ROOT / "src" / "crossvet").glob("*.py"))
    names = set(re.findall(r'"((?:CROSSVET|OPENAI|ANTHROPIC|GOOGLE|XAI|OPENROUTER|OLLAMA|LOCAL)_[A-Z_]+)"', code))
    names -= {"CROSSVET_CHAT_"}
    missing = {n for n in names if f"{n}=" not in env}
    assert not missing, missing
