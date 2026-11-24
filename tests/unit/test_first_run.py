"""What a new user meets first after installing from GitHub."""

from __future__ import annotations

import os

import pytest

from open_deep_research import cli, doctor
from open_deep_research.chat import cli as chat_cli
from open_deep_research.chat.hub import Attempt, failure_message
from open_deep_research.envfile import load_env


def test_env_file_in_the_working_folder_is_read(tmp_path, monkeypatch):
    """An installed package must read .env from the folder it is run in, not from site-packages."""
    (tmp_path / ".env").write_text("CROSSVET_TEST_ONLY_SETTING=from-working-folder\n")
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("CROSSVET_TEST_ONLY_SETTING", raising=False)
    assert load_env() == str(tmp_path / ".env")
    assert os.environ["CROSSVET_TEST_ONLY_SETTING"] == "from-working-folder"
    monkeypatch.delenv("CROSSVET_TEST_ONLY_SETTING")


def test_env_file_does_not_override_the_environment(tmp_path, monkeypatch):
    (tmp_path / ".env").write_text("CROSSVET_TEST_ONLY_SETTING=from-file\n")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("CROSSVET_TEST_ONLY_SETTING", "from-shell")
    load_env()
    assert os.environ["CROSSVET_TEST_ONLY_SETTING"] == "from-shell"


def test_tools_see_the_env_file(tmp_path, monkeypatch):
    """`crossvet <tool>` loads .env before handing over, so every tool reads the same file."""
    (tmp_path / ".env").write_text("CROSSVET_TEST_ONLY_SETTING=seen-by-tool\n")
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("CROSSVET_TEST_ONLY_SETTING", raising=False)
    seen = {}

    def fake_tool(name, rest):
        seen["value"] = os.environ.get("CROSSVET_TEST_ONLY_SETTING")
        return 0

    monkeypatch.setattr(cli, "_tool", fake_tool)
    assert cli.main(["scan", "page.html"]) == 0
    assert seen["value"] == "seen-by-tool"
    monkeypatch.delenv("CROSSVET_TEST_ONLY_SETTING")


def test_bare_crossvet_prints_help(capsys, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert cli.main([]) == 0
    out = capsys.readouterr().out
    assert "start here:" in out and "crossvet chat" in out


def test_version_flag(capsys, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    with pytest.raises(SystemExit) as stop:
        cli.main(["--version"])
    assert stop.value.code == 0
    assert capsys.readouterr().out.startswith("crossvet ")


def test_help_lists_each_tool_once():
    start, more = cli.START_HERE.split("more tools")
    for name in cli.TOOLS:
        assert (f"crossvet {name} " in start) != (f"crossvet {name} " in more), name


def test_doctor_says_what_to_do_next(capsys, monkeypatch):
    monkeypatch.setattr(doctor, "check", lambda: [doctor.Finding("FAIL", "research model: needs a key")])
    monkeypatch.setattr("sys.argv", ["crossvet-doctor"])
    assert doctor.main() == 1
    assert "Next: run `crossvet setup`" in capsys.readouterr().out


def test_one_missing_key_is_one_line():
    attempts = [Attempt(f"openrouter:v/m{i}", False, "OPENROUTER_API_KEY is not set", None, 0.0) for i in range(4)]
    message = failure_message(attempts)
    assert message.startswith("OPENROUTER_API_KEY is not set: add it to .env")
    assert "m0" not in message


def test_mixed_failures_are_listed():
    attempts = [Attempt("openrouter:v/a", False, "OPENROUTER_API_KEY is not set", None, 0.0),
                Attempt("openai:b", False, "HTTP 500", None, 0.0)]
    assert failure_message(attempts).startswith("every model failed: ")


def test_chat_doctor_groups_missing_keys(capsys, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    for name in ("OPENROUTER_API_KEY", "OPENAI_API_KEY", "ANTHROPIC_API_KEY", "GOOGLE_API_KEY", "XAI_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    (tmp_path / "crossvet-chat.toml").write_text(
        '[slots]\nquick = ["openrouter:a/q"]\nbalanced = ["openrouter:a/b", "openrouter:c/b"]\nstrong = ["openrouter:a/s"]\n')
    monkeypatch.setenv("CROSSVET_CHAT_CONFIG", str(tmp_path / "crossvet-chat.toml"))
    assert chat_cli.main(["doctor"]) == 1
    out = capsys.readouterr().out
    assert out.count("OPENROUTER_API_KEY is not set") == 1
    assert "(4 model(s) need it)" in out
    assert "ollama no key needed" in out
    assert out.strip().endswith("1 problem(s)")
