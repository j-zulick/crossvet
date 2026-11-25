"""The base install (no research extra): what runs, what explains itself, and the LangGraph config."""

from __future__ import annotations

import json
import tomllib
from pathlib import Path

from open_deep_research import cli

ROOT = Path(__file__).resolve().parents[2]
PROJECT = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]


def test_base_dependencies_stay_small():
    names = sorted(spec.split(">")[0].split("<")[0].split("=")[0].split("[")[0] for spec in PROJECT["dependencies"])
    assert names == ["httpx", "mcp", "python-dotenv"]


def test_research_commands_say_what_to_install(monkeypatch, capsys, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(cli, "research_installed", lambda: False)
    assert cli.main(["research", "a question"]) == 2
    assert 'crossvet[research]' in capsys.readouterr().err
    assert cli.main(["bench"]) == 2


def test_light_commands_do_not_need_the_research_extra(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(cli, "research_installed", lambda: False)
    ran = []
    monkeypatch.setattr(cli, "_tool", lambda name, rest: ran.append(name) or 0)
    for name in cli.LIGHT:
        assert cli.main([name]) == 0
    assert ran == list(cli.LIGHT)


def test_langgraph_configs_install_the_research_extra():
    """LangGraph installs "." without extras, so its configs list the research packages themselves."""
    research = PROJECT["optional-dependencies"]["research"]
    for name in ("langgraph.json", "langgraph.local.json"):
        deps = json.loads((ROOT / name).read_text())["dependencies"]
        assert deps == [".", *research], name


def test_chat_doctor_flags_langfuse_keys_without_the_package(monkeypatch, capsys, tmp_path):
    from open_deep_research.chat import cli as chat_cli
    from open_deep_research.chat import record

    monkeypatch.chdir(tmp_path)
    (tmp_path / "crossvet-chat.toml").write_text('[slots]\nquick = ["ollama:q"]\nbalanced = ["ollama:b"]\nstrong = ["ollama:s"]\n')
    monkeypatch.setenv("CROSSVET_CHAT_CONFIG", str(tmp_path / "crossvet-chat.toml"))
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk-test")
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk-test")
    monkeypatch.setattr(record, "langfuse_installed", lambda: False)
    assert chat_cli.main(["doctor"]) == 1
    out = capsys.readouterr().out
    assert "langfuse package is not installed" in out and "crossvet[langfuse]" in out
