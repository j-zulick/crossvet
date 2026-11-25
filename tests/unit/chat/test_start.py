"""`crossvet chat start`: one step from a folder with keys to the settings Hermes and Cursor need."""

from __future__ import annotations

import json

from crossvet.chat import cli

TOML = '[slots]\nquick = ["openrouter:a/q"]\nbalanced = ["openrouter:a/b"]\nstrong = ["openrouter:a/s"]\n'


def setup_folder(tmp_path, monkeypatch, key: bool):
    monkeypatch.chdir(tmp_path)
    for name in ("OPENROUTER_API_KEY", "OPENAI_API_KEY", "ANTHROPIC_API_KEY", "GOOGLE_API_KEY", "XAI_API_KEY",
                 "CROSSVET_CHAT_TOKEN", "CROSSVET_CHAT_CONFIG"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("CROSSVET_CHAT_DB", str(tmp_path / "chat.db"))
    (tmp_path / "crossvet-chat.toml").write_text(TOML)
    if key:
        monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")


def test_start_prints_hermes_and_cursor_settings(tmp_path, monkeypatch, capsys):
    setup_folder(tmp_path, monkeypatch, key=True)
    assert cli.main(["start", "--no-serve", "--port", "9999"]) == 0
    out = capsys.readouterr().out
    assert "base URL   http://127.0.0.1:9999/v1" in out and "model      auto" in out
    assert "any text (not checked on this computer)" in out
    cursor = json.loads(out[out.index("{"): out.index("Pi (MCP tools)")].strip())
    assert cursor["mcpServers"]["crossvet"]["args"][1].endswith("crossvet chat mcp")
    assert str(tmp_path) in cursor["mcpServers"]["crossvet"]["args"][1]
    pi = json.loads(out[out.index("{", out.index("Pi (MCP tools)")): out.index("Activity page")].strip())
    assert pi["mcpServers"]["crossvet"]["args"] == cursor["mcpServers"]["crossvet"]["args"]


def test_write_pi_keeps_other_servers_and_a_backup(tmp_path):
    target = tmp_path / ".pi" / "agent" / "mcp.json"
    target.parent.mkdir(parents=True)
    target.write_text(json.dumps({"mcpServers": {"docs": {"url": "https://example.com/mcp"}}, "other": 1}))
    message = cli.write_pi_config(tmp_path / "work", target)
    data = json.loads(target.read_text())
    assert message.startswith("added") and data["mcpServers"]["docs"] == {"url": "https://example.com/mcp"} and data["other"] == 1
    assert "crossvet chat mcp" in data["mcpServers"]["crossvet"]["args"][1]
    assert json.loads(target.with_suffix(".json.bak").read_text())["mcpServers"].keys() == {"docs"}
    assert cli.write_pi_config(tmp_path / "work", target).startswith("updated")
    target.write_text("{not json")
    import pytest

    with pytest.raises(ValueError, match="not valid JSON"):
        cli.write_pi_config(tmp_path, target)


def test_start_names_the_token_when_one_is_set(tmp_path, monkeypatch, capsys):
    setup_folder(tmp_path, monkeypatch, key=True)
    monkeypatch.setenv("CROSSVET_CHAT_TOKEN", "secret-value-not-printed")
    assert cli.main(["start", "--no-serve"]) == 0
    out = capsys.readouterr().out
    assert "the value of CROSSVET_CHAT_TOKEN" in out and "secret-value-not-printed" not in out


def test_start_without_keys_says_what_to_add(tmp_path, monkeypatch, capsys):
    setup_folder(tmp_path, monkeypatch, key=False)
    assert cli.main(["start", "--no-serve"]) == 1
    assert "Add OPENROUTER_API_KEY" in capsys.readouterr().err


def test_start_writes_a_config_when_there_is_none(tmp_path, monkeypatch, capsys):
    setup_folder(tmp_path, monkeypatch, key=False)
    (tmp_path / "crossvet-chat.toml").unlink()
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    code = cli.main(["start", "--no-serve"])
    assert (tmp_path / "crossvet-chat.toml").exists()
    assert code == 0 and "wrote crossvet-chat.toml from your keys" in capsys.readouterr().out


def test_load_env_reads_the_earlier_local_model_names(tmp_path, monkeypatch):
    from crossvet.chat import cli as chat_cli

    for name in ("LOCAL_BASE_URL", "LOCAL_API_KEY", "LOCAL_LLM_BASE_URL", "LOCAL_LLM_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    env = tmp_path / ".env"
    env.write_text("LOCAL_LLM_BASE_URL=http://localhost:1234/v1\nLOCAL_LLM_API_KEY=not-needed\n")
    names = chat_cli.load_env(str(env))
    assert "LOCAL_BASE_URL" in names and "LOCAL_API_KEY" in names
    import os
    assert os.environ["LOCAL_BASE_URL"] == "http://localhost:1234/v1"
