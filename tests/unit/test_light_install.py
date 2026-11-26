"""The base install: three dependencies and one command."""

from __future__ import annotations

import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PROJECT = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]


def test_base_dependencies_stay_small():
    names = sorted(spec.split(">")[0].split("<")[0].split("=")[0].split("[")[0] for spec in PROJECT["dependencies"])
    assert names == ["httpx", "mcp", "python-dotenv"]


def test_one_command_and_no_optional_parts():
    assert PROJECT["scripts"] == {"crossvet": "crossvet.cli:main"}
    assert PROJECT["optional-dependencies"]["all"] == []


def test_keys_load_from_dot_env_without_overriding_the_environment(tmp_path, monkeypatch):
    from crossvet.config import load_env

    (tmp_path / ".env").write_text("OPENAI_API_KEY=from-file\nXAI_API_KEY=from-file\n")
    monkeypatch.setenv("OPENAI_API_KEY", "from-env")
    monkeypatch.setenv("XAI_API_KEY", "")
    monkeypatch.delenv("XAI_API_KEY")  # restored to unset after the test
    assert load_env() == [".env"]
    import os

    assert os.environ["OPENAI_API_KEY"] == "from-env" and os.environ["XAI_API_KEY"] == "from-file"
