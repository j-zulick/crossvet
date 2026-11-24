"""Version caps that keep a fresh install (which does not read uv.lock) working."""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

PYPROJECT = tomllib.loads((Path(__file__).resolve().parents[2] / "pyproject.toml").read_text())


def _specs() -> list[str]:
    project = PYPROJECT["project"]
    return list(project["dependencies"]) + [s for extra in project.get("optional-dependencies", {}).values() for s in extra]


def test_mcp_is_capped_below_2():
    """mcp 2 renamed FastMCP and other APIs that Crossvet and langchain-mcp-adapters import (found Nov 24, 2026)."""
    mcp = [s for s in _specs() if re.match(r"^mcp\b", s)]
    assert mcp and all("<2" in s for s in mcp), mcp
