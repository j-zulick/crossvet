"""The commands added for choosing, rating, comparing and looking after the local files."""

from __future__ import annotations

import pytest

from crossvet import cli
from crossvet.core import Crossvet


@pytest.fixture
def terminal(monkeypatch, tmp_path, fake):
    monkeypatch.setenv("OPENAI_API_KEY", "x")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "x")
    monkeypatch.setenv("CROSSVET_DB", str(tmp_path / "chat.db"))
    real = Crossvet.__init__
    monkeypatch.setattr(Crossvet, "__init__", lambda self, *a, **k: real(self, *a, streamer=fake.stream, **k))
    return fake


def test_route_explains_without_calling(terminal, capsys):
    assert cli.main(["route", "Fix the race condition in this Go worker pool"]) == 0
    assert "anthropic:claude-opus-5-5 answers" in capsys.readouterr().out and terminal.calls == []
    assert cli.main(["chat", "route", "-m", "crossvet/cheapest", "Fix the bug"]) == 0
    assert "goal: cheapest" in capsys.readouterr().out


def test_ask_auto_why_rate_and_tune(terminal, capsys):
    terminal.on("anthropic:claude-haiku-5-5", "34236")
    assert cli.main(["ask", "-m", "auto", "What is the ZIP code for 707 S Washington Blvd, Sarasota?"]) == 0
    assert "auto: quick slot" in capsys.readouterr().err
    assert cli.main(["why"]) == 0
    assert "anthropic:claude-haiku-5-5 (kind quick, slot quick" in capsys.readouterr().out
    assert cli.main(["rate", "good", "right ZIP"]) == 0 and "rated #2 good" in capsys.readouterr().out
    assert cli.main(["tune"]) == 0 and "quick      anthropic:claude-haiku-5-5 1/1" in capsys.readouterr().out
    assert cli.main(["tune", "accept"]) == 2


def test_compare_notes_report_export_and_backup(terminal, tmp_path, capsys):
    terminal.on("openai:gpt-6-luna", "Low.")
    terminal.on("anthropic:claude-haiku-5-5", "Low for its age.")
    assert cli.main(["compare", "-m", "luna", "-m", "haiku", "Is 48,000 miles high for a 2019 CR-V?"]) == 0
    assert "## anthropic:claude-haiku-5-5\nLow for its age." in capsys.readouterr().out
    assert cli.main(["note", "Venice Honda doc fee is $998", "--tags", "fees"]) == 0
    assert cli.main(["notes", "doc", "fee"]) == 0 and "Venice Honda" in capsys.readouterr().out
    assert cli.main(["report", "--days", "0"]) == 0 and "| `openai:gpt-6-luna` | 1 |" in capsys.readouterr().out
    assert cli.main(["export"]) == 0 and capsys.readouterr().out.count("\n") == 2
    assert cli.main(["dashboard", "--out", str(tmp_path / "d.html")]) == 0
    assert cli.main(["backup", str(tmp_path / "bk")]) == 0 and (tmp_path / "bk" / "lab.db").is_file()
    assert cli.main(["restore", str(tmp_path / "bk")]) == 1  # the log has turns: needs --force
    assert "--force" in capsys.readouterr().err
    assert cli.main(["prune"]) == 0 and cli.main(["sync"]) == 0
    assert "not set up" in capsys.readouterr().out


def test_terminal_chat_why_good_and_retry(terminal, monkeypatch, capsys):
    terminal.on("anthropic:claude-haiku-5-5", "Low.")
    terminal.on("anthropic:claude-sonnet-5-5", "It is low for a five-year-old SUV.")
    lines = iter(["Is 48,000 miles high for a 2019 CR-V?", "/why", "/good", "/retry stronger", "/quit"])
    monkeypatch.setattr("builtins.input", lambda _: next(lines))
    assert cli.main(["chat", "-m", "auto"]) == 0
    out = capsys.readouterr().out
    assert "anthropic:claude-haiku-5-5 (kind quick, slot quick)" in out and "rated #2" in out
    assert "crossvet/balanced> It is low" in out
