"""The base install: three dependencies, the `crossvet` front door, and the Langfuse hint."""

from __future__ import annotations

import tomllib
from pathlib import Path

from crossvet import cli

ROOT = Path(__file__).resolve().parents[2]
PROJECT = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]


def test_base_dependencies_stay_small():
    names = sorted(spec.split(">")[0].split("<")[0].split("=")[0].split("[")[0] for spec in PROJECT["dependencies"])
    assert names == ["httpx", "mcp", "python-dotenv"]


def test_front_door_runs_the_chat_and_prints_help(monkeypatch, capsys):
    ran = []
    monkeypatch.setattr("crossvet.chat.cli.main", lambda argv: ran.append(argv) or 0)
    assert cli.main(["chat", "route", "hello"]) == 0
    assert ran == [["route", "hello"]]
    assert cli.main([]) == 0 and "crossvet chat start" in capsys.readouterr().out
    assert cli.main(["research"]) == 2
    capsys.readouterr()
    assert cli.main(["--version"]) == 0 and capsys.readouterr().out.startswith("crossvet ")


def test_chat_doctor_flags_langfuse_keys_without_the_package(monkeypatch, capsys, tmp_path):
    from crossvet.chat import cli as chat_cli
    from crossvet.chat import record

    monkeypatch.chdir(tmp_path)
    (tmp_path / "crossvet-chat.toml").write_text('[slots]\nquick = ["ollama:q"]\nbalanced = ["ollama:b"]\nstrong = ["ollama:s"]\n')
    monkeypatch.setenv("CROSSVET_CHAT_CONFIG", str(tmp_path / "crossvet-chat.toml"))
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk-test")
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk-test")
    monkeypatch.setattr(record, "langfuse_installed", lambda: False)
    assert chat_cli.main(["doctor"]) == 1
    out = capsys.readouterr().out
    assert "langfuse package is not installed" in out and "crossvet[langfuse]" in out
