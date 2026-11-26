"""The MCP tools, the command line, and the 1.x spellings."""

from __future__ import annotations

import pytest

from crossvet import cli, mcp_server
from crossvet.core import Crossvet
from crossvet.providers import ProviderError

Q = "Summarize this listing in one line: 2020 Ford F-150 XLT, 41,000 mi, $34,500, Sarasota."


def test_the_three_mcp_tools(cv, fake):
    tools = mcp_server.tools(cv)
    assert sorted(tools) == ["ask_model", "list_models", "recent_turns"]
    assert "anthropic:claude-opus-5-5 (claude)" in tools["list_models"]()
    fake.on("openai:gpt-6-luna", "2020 F-150 XLT, 41k mi, $34,500.")
    text = tools["ask_model"](Q, model="luna", system="Be brief.")
    assert text.startswith("2020 F-150 XLT") and "[crossvet: openai:gpt-6-luna" in text
    assert fake.calls[-1][1][0] == {"role": "system", "content": "Be brief."}
    recent = tools["recent_turns"](5)
    assert "[openai:gpt-6-luna]" in recent and "question via mcp" in recent


def test_mcp_ask_reports_problems_as_text(cv, fake):
    tools = mcp_server.tools(cv)
    assert "Crossvet could not get an answer from nope" in tools["ask_model"](Q, model="nope")
    fake.on("openai:gpt-6.1-sol", ProviderError("HTTP 500"))
    assert "HTTP 500" in tools["ask_model"](Q, model="gpt")
    assert "limit" in tools["ask_model"]("x" * (mcp_server.MAX_TEXT + 1))
    assert mcp_server.tools(Crossvet(cv.config, type(cv.store)()))["recent_turns"]() == "No turns yet."


def test_the_mcp_server_registers_exactly_three_tools(cv):
    import asyncio

    server = mcp_server.build_server(cv)
    names = sorted(t.name for t in asyncio.run(server.list_tools()))
    assert names == ["ask_model", "list_models", "recent_turns"]


def test_mcp_http_stays_on_this_computer(capsys):
    assert mcp_server.main(http=True, host="0.0.0.0") == 2


@pytest.mark.parametrize("old", ["route", "bench", "compare", "backup", "routes"])
def test_removed_1x_commands_say_why_and_exit_1(old, capsys):
    assert cli.main(["chat", old, "Fix the race condition"]) == 1
    assert "removed in Crossvet 2.0" in capsys.readouterr().err


def test_1x_spellings_of_kept_commands_still_work():
    assert cli.normalize(["chat", "start", "--no-serve"]) == ["start", "--no-serve"]
    assert cli.normalize(["chat", "mcp"]) == ["mcp"]
    assert cli.normalize(["chat", "--version"]) == ["--version"]
    assert cli.normalize(["chat", "-m", "gpt"]) == ["chat", "-m", "gpt"]
    assert cli.normalize(["chat"]) == ["chat"]


def test_version_and_help(capsys):
    with pytest.raises(SystemExit) as done:
        cli.main(["chat", "--version"])
    assert done.value.code == 0 and capsys.readouterr().out.startswith("crossvet 2")
    assert cli.main([]) == 0 and "crossvet start" in capsys.readouterr().out


def test_start_without_keys_says_what_to_add(capsys):
    assert cli.main(["start", "--no-serve"]) == 1
    assert "set at least one key" in capsys.readouterr().err


def test_start_prints_every_apps_settings(monkeypatch, capsys):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    assert cli.main(["start", "--no-serve"]) == 0
    out = capsys.readouterr().out
    for text in ("http://127.0.0.1:8787/v1", "provider: custom", "claude mcp add --scope user crossvet",
                 "codex mcp add crossvet", '"mcpServers"', "anthropic:claude-sonnet-5-5"):
        assert text in out


def test_init_writes_a_file_and_will_not_overwrite(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    target = tmp_path / "c.toml"
    assert cli.main(["init", "--path", str(target)]) == 0
    assert 'default_model = "openai:gpt-6.1-terra"' in target.read_text()
    assert cli.main(["init", "--path", str(target)]) == 1
    monkeypatch.setenv("CROSSVET_CONFIG", str(target))
    monkeypatch.setenv("CROSSVET_DB", str(tmp_path / "log.db"))
    assert cli.main(["doctor"]) == 0
    assert "ok" in capsys.readouterr().out


def test_doctor_points_out_1x_leftovers(monkeypatch, tmp_path, capsys):
    (tmp_path / "crossvet-chat.toml").write_text("[slots]\n")
    monkeypatch.setenv("CROSSVET_CHAT_TOKEN", "x")
    monkeypatch.setenv("CROSSVET_DB", str(tmp_path / "log.db"))
    assert cli.main(["doctor"]) == 1  # no keys
    out = capsys.readouterr().out
    assert "1.x settings file" in out and "CROSSVET_CHAT_TOKEN" in out and "add a key" in out


def test_ask_cost_and_log_from_the_terminal(monkeypatch, tmp_path, capsys, fake):
    from crossvet import core

    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("CROSSVET_DB", str(tmp_path / "log.db"))
    real = core.Crossvet.__init__
    monkeypatch.setattr(core.Crossvet, "__init__", lambda self, *a, **k: real(self, *a, streamer=fake.stream, **k))
    fake.on("openai:gpt-6-luna", "One line.")
    assert cli.main(["ask", "-m", "luna", Q]) == 0
    captured = capsys.readouterr()
    assert captured.out == "One line." and "openai:gpt-6-luna" in captured.err
    assert cli.main(["cost"]) == 0 and "openai:gpt-6-luna" in capsys.readouterr().out
    assert cli.main(["log", "-n", "2"]) == 0 and "One line." in capsys.readouterr().out
    assert cli.main(["ask", "-m", "nope", Q]) == 1


def test_terminal_chat_switches_models(monkeypatch, tmp_path, capsys, fake):
    from crossvet import core

    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("CROSSVET_DB", str(tmp_path / "log.db"))
    real = core.Crossvet.__init__
    monkeypatch.setattr(core.Crossvet, "__init__", lambda self, *a, **k: real(self, *a, streamer=fake.stream, **k))
    lines = iter(["hello", "/model sol", "/model nope", "again", "/cost", "/quit"])
    monkeypatch.setattr("builtins.input", lambda _: next(lines))
    assert cli.main(["chat"]) == 0
    assert [m for m, _ in fake.calls] == ["openai:gpt-6.1-terra", "openai:gpt-6.1-sol"]
    assert [m["content"] for m in fake.calls[1][1]] == ["hello", "ok", "again"]
    out = capsys.readouterr().out
    assert "unknown model 'nope'" in out and "This conversation:" in out and "now talking to openai:gpt-6.1-sol" in out
