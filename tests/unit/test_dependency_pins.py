"""Version caps that keep a fresh install (which does not read uv.lock) working."""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

PYPROJECT = tomllib.loads((Path(__file__).resolve().parents[2] / "pyproject.toml").read_text())


def _specs() -> list[str]:
    project = PYPROJECT["project"]
    return list(project["dependencies"]) + [s for extra in project.get("optional-dependencies", {}).values() for s in extra]


def test_mcp_1_and_2_are_both_allowed():
    """Chat runs on MCP SDK 1.x and 2.x; the cap stops an untested 3.x."""
    mcp = [s for s in _specs() if re.match(r"^mcp\b", s)]
    assert mcp and all("<3" in s and "<2" not in s for s in mcp), mcp
