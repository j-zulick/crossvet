"""`crossvet chat start`: one step from a folder with keys to the settings Hermes and Cursor need."""

from __future__ import annotations

import json

from open_deep_research.chat import cli

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
    cursor = json.loads(out[out.index("{"): out.index("Activity page")].strip())
    assert cursor["mcpServers"]["crossvet"]["args"][1].endswith("crossvet chat mcp")
    assert str(tmp_path) in cursor["mcpServers"]["crossvet"]["args"][1]


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
