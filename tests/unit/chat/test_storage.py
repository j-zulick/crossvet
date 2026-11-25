"""Backup, restore and prune of the chat store; the request-size and timeout limits."""

from __future__ import annotations

import sqlite3
import time

import pytest
from starlette.testclient import TestClient

from open_deep_research.chat import cli, providers, storage
from open_deep_research.chat.config import parse
from open_deep_research.chat.hub import Hub
from open_deep_research.chat.memory import Memory
from open_deep_research.chat.record import Recorder, trace_id_for
from open_deep_research.chat.server import create_app

from .conftest import CONFIG


def store_with_history(path, models) -> Hub:
    hub = Hub(config=parse(CONFIG, "test"), memory=Memory(str(path)), caller=models, recorder=Recorder())
    old = hub.ask("Fix the race condition in this Go worker pool", slot="strong")
    hub.feedback(False, turn_id=old.turn_id)
    hub.memory.add_note("launch", "the launch date is March 3", author="test")
    hub.tuning.change("code", "you", "my call", models=["openai:big"])
    return hub


def age_everything(path, days):
    """Move every turn and rating ``days`` into the past (tests only: the store refuses updates otherwise)."""
    db = sqlite3.connect(path)
    for table in ("turns", "feedback"):
        db.execute(f"DROP TRIGGER IF EXISTS {table}_no_update")
        db.execute(f"UPDATE {table} SET ts = ts - ?", (days * 86400,))
    db.commit()
    db.close()
    Memory(str(path)).db.close()  # put the triggers back


def test_backup_copies_and_checks(tmp_path, models):
    hub = store_with_history(tmp_path / "chat.db", models)
    hub.memory.db.close()
    path, found = storage.backup(tmp_path / "chat.db", tmp_path / "copy.db")
    assert found == {"turns": 2, "notes": 1, "ratings": 1} and storage.problems(path) == []
    with pytest.raises(FileExistsError):
        storage.backup(tmp_path / "chat.db", tmp_path / "copy.db")


def test_problems_names_what_is_wrong(tmp_path):
    (tmp_path / "junk.db").write_text("not a database")
    assert "not a SQLite database" in storage.problems(tmp_path / "junk.db")[0]
    other = sqlite3.connect(tmp_path / "other.db")
    other.execute("CREATE TABLE t (x)")
    other.close()
    assert "not a Crossvet chat store" in storage.problems(tmp_path / "other.db")[0]
    assert "does not exist" in storage.problems(tmp_path / "missing.db")[0]


def test_restore_saves_the_current_store_first(tmp_path, models):
    hub = store_with_history(tmp_path / "chat.db", models)
    hub.memory.db.close()
    backup, _ = storage.backup(tmp_path / "chat.db", tmp_path / "copy.db")
    later = Hub(config=parse(CONFIG, "test"), memory=Memory(str(tmp_path / "chat.db")), caller=models, recorder=Recorder())
    later.ask("Write a short thank-you note")
    later.memory.db.close()
    saved, found = storage.restore(backup, tmp_path / "chat.db")
    assert found["turns"] == 2 and saved is not None and storage.problems(saved) == []
    assert storage.counts(sqlite3.connect(saved))["turns"] == 4


def test_restore_refuses_a_bad_file(tmp_path):
    (tmp_path / "junk.db").write_text("x")
    with pytest.raises(RuntimeError, match="not restoring"):
        storage.restore(tmp_path / "junk.db", tmp_path / "chat.db")


def test_prune_keeps_recent_turns_everything_else_and_the_store_id(tmp_path, models):
    path = tmp_path / "chat.db"
    hub = store_with_history(path, models)
    store_id = hub.memory.id
    hub.memory.db.close()
    age_everything(path, 100)
    recent = Hub(config=parse(CONFIG, "test"), memory=Memory(str(path)), caller=models, recorder=Recorder())
    kept_answer = recent.ask("Fix the race condition in this Go worker pool", slot="strong")
    recent.feedback(True, turn_id=kept_answer.turn_id)
    recent.memory.db.close()

    result = storage.prune(path, older_than_days=30)
    assert (result.kept_turns, result.removed_turns, result.removed_ratings) == (2, 2, 1)
    assert storage.problems(result.backup) == [] and storage.counts(sqlite3.connect(result.backup))["turns"] == 4

    after = Hub(config=parse(CONFIG, "test"), memory=Memory(str(path)), caller=models, recorder=Recorder())
    assert after.memory.id == store_id
    assert trace_id_for(after.memory.id, kept_answer.turn_id) == recent.trace_id(kept_answer.turn_id)
    assert [r.value for r in after.memory.ratings(since=0)] == [1.0]
    found = after.memory.search("launch date")  # notes and their search index survive
    assert any("March 3" in str(n) for n in found["notes"])
    assert after.tuning.current().entries["code"].models == ["openai:big"]
    with pytest.raises(sqlite3.DatabaseError, match="append-only"):
        after.memory.db.execute("DELETE FROM turns")
    assert after.ask("Fix the race condition in this Go worker pool", slot="strong").turn_id > kept_answer.turn_id


def test_prune_needs_a_positive_number_of_days(tmp_path, models):
    hub = store_with_history(tmp_path / "chat.db", models)
    hub.memory.db.close()
    with pytest.raises(ValueError):
        storage.prune(tmp_path / "chat.db", 0)


def test_cli_restore_and_prune_ask_for_yes(tmp_path, models, monkeypatch, capsys):
    path = tmp_path / "chat.db"
    hub = store_with_history(path, models)
    hub.memory.db.close()
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("CROSSVET_CHAT_DB", str(path))
    monkeypatch.setenv("CROSSVET_CHAT_CONFIG", str(tmp_path / "none.toml"))
    (tmp_path / "none.toml").write_text("")
    assert cli.main(["backup", str(tmp_path / "b.db")]) == 0
    assert "backed up 2 turns, 1 notes and 1 ratings" in capsys.readouterr().out
    assert cli.main(["restore", str(tmp_path / "b.db")]) == 2 and "--yes" in capsys.readouterr().out
    assert cli.main(["restore", str(tmp_path / "b.db"), "--yes"]) == 0
    assert cli.main(["prune", "--older-than", "30"]) == 2
    assert cli.main(["prune", "--older-than", "30", "--yes"]) == 0
    assert "kept 2 turns; removed 0 turns" in capsys.readouterr().out


def test_server_refuses_requests_over_the_size_limit(models):
    cfg = parse({**CONFIG, "limits": {**CONFIG["limits"], "max_request_bytes": 200}}, "test")
    hub = Hub(config=cfg, memory=Memory(":memory:"), caller=models, recorder=Recorder())
    client = TestClient(create_app(hub))
    big = client.post("/v1/chat/completions", json={"model": "auto", "messages": [{"role": "user", "content": "x" * 500}]})
    assert big.status_code == 413 and big.json()["error"]["type"] == "request_too_large"
    small = client.post("/v1/chat/completions", json={"model": "auto", "messages": [{"role": "user", "content": "hi"}]})
    assert small.status_code == 200


def test_timeout_setting_reaches_every_call(models):
    cfg = parse({**CONFIG, "limits": {**CONFIG["limits"], "timeout_seconds": 7}}, "test")
    Hub(config=cfg, memory=Memory(":memory:"), caller=models, recorder=Recorder())
    assert providers.TIMEOUT.read == 7 and providers.TIMEOUT.connect == 7
    providers.set_timeout(120)
    with pytest.raises(ValueError, match="more than 0"):
        parse({**CONFIG, "limits": {"timeout_seconds": 0}}, "test")


def test_backing_up_a_busy_store_is_quick(tmp_path, models):
    hub = Hub(config=parse(CONFIG, "test"), memory=Memory(str(tmp_path / "chat.db")), caller=models, recorder=Recorder())
    for i in range(300):
        hub.memory.add_turn(f"t{i % 20}", "test", "user", f"question {i} " * 20)
    hub.memory.db.close()
    started = time.monotonic()
    storage.backup(tmp_path / "chat.db", tmp_path / "copy.db")
    assert time.monotonic() - started < 5
