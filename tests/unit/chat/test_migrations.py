"""The store upgrades in place, backs up first, and refuses a store from a newer release (offline)."""

from __future__ import annotations

import sqlite3

import pytest

from crossvet.chat import migrations
from crossvet.chat.memory import Memory


def test_a_new_store_and_an_old_one_get_the_current_version(tmp_path):
    assert migrations.version(Memory(str(tmp_path / "new.db")).db) == migrations.latest()
    old = tmp_path / "old.db"
    made_before = Memory(str(old))
    made_before.add_turn("t", "cli", "user", "hello from 0.8")
    made_before.db.execute("PRAGMA user_version = 0")  # as 0.8.0 left it: no version recorded
    made_before.db.commit()
    made_before.db.close()
    reopened = Memory(str(old))
    assert migrations.version(reopened.db) == migrations.latest()
    assert reopened.turns("t")[0].content == "hello from 0.8"
    assert not list(tmp_path.glob("old.before-upgrade-*"))  # the baseline changes nothing, so no backup


def test_a_schema_change_runs_once_with_a_backup(tmp_path):
    path = tmp_path / "chat.db"
    store = Memory(str(path))
    store.add_turn("t", "cli", "user", "keep me")
    calls = []

    def add_column(db):
        calls.append(1)
        db.execute("ALTER TABLE turns ADD COLUMN language TEXT NOT NULL DEFAULT ''")

    steps = [*migrations.STEPS, ("add turns.language", add_column)]
    assert migrations.upgrade(store.db, str(path), steps) == ["add turns.language"]
    assert migrations.upgrade(store.db, str(path), steps) == []  # already done
    assert calls == [1] and migrations.version(store.db) == 2
    assert "language" in [r[1] for r in store.db.execute("PRAGMA table_info(turns)")]
    backup = tmp_path / "chat.before-upgrade-v2.db"
    assert backup.is_file() and sqlite3.connect(backup).execute("SELECT content FROM turns").fetchone()[0] == "keep me"


def test_a_failed_step_leaves_the_version_and_data_alone(tmp_path):
    store = Memory(str(tmp_path / "chat.db"))
    store.db.isolation_level = None

    def broken(db):
        db.execute("CREATE TABLE half (x)")
        raise RuntimeError("step failed")

    with pytest.raises(RuntimeError, match="step failed"):
        migrations.upgrade(store.db, str(tmp_path / "chat.db"), [*migrations.STEPS, ("broken", broken)])
    assert migrations.version(store.db) == 1
    assert "half" not in [r[0] for r in store.db.execute("SELECT name FROM sqlite_master")]


def test_a_store_from_a_newer_release_is_refused(tmp_path):
    path = tmp_path / "chat.db"
    store = Memory(str(path))
    store.db.execute("PRAGMA user_version = 99")
    store.db.commit()
    store.db.close()
    with pytest.raises(migrations.StoreTooNew, match="newer Crossvet"):
        Memory(str(path))
