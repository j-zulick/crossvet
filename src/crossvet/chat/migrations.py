"""Upgrade the chat store in place when a newer Crossvet opens it.

The store keeps its schema version in SQLite's ``user_version``. On open, every step newer than
that version runs in order, each in its own transaction, and the version moves forward only when
its step succeeds. Before the first step that changes a file store, a backup is saved beside it
(``chat.before-upgrade-v<N>.db``). A store whose version is newer than this release knows is
refused, rather than opened and possibly damaged.

To change the schema: append a step to ``STEPS`` (never edit or reorder an old one) and add a test
that opens a store made before it. Version 1 is the 0.9.0 schema itself, so its step only records
the version.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Callable
from pathlib import Path


def _baseline(db: sqlite3.Connection) -> None:
    """Version 1: the tables as of 0.9.0 (created by ``memory.SCHEMA``); nothing to change."""


STEPS: list[tuple[str, Callable[[sqlite3.Connection], None]]] = [
    ("0.9.0 schema", _baseline),
]


class StoreTooNew(RuntimeError):
    """The store was made by a newer Crossvet than this one."""


def version(db: sqlite3.Connection) -> int:
    """Return the store's schema version (0 for a store made before versions were recorded)."""
    return int(db.execute("PRAGMA user_version").fetchone()[0])


def latest() -> int:
    """Return the schema version this release writes."""
    return len(STEPS)


def upgrade(db: sqlite3.Connection, path: str = ":memory:", steps: list | None = None) -> list[str]:
    """Run the steps newer than the store's version; return their names. Raise ``StoreTooNew`` for a newer store."""
    steps = STEPS if steps is None else steps
    current = version(db)
    if current > len(steps):
        raise StoreTooNew(f"this chat store is schema version {current}, made by a newer Crossvet (this one knows "
                          f"{len(steps)}); update Crossvet, or open a backup")
    done: list[str] = []
    for number, (name, step) in enumerate(steps[current:], start=current + 1):
        if path != ":memory:" and step is not _baseline and not done and Path(path).is_file():
            from crossvet.chat import storage

            db.commit()
            storage.backup(path, Path(path).with_name(f"{Path(path).stem}.before-upgrade-v{number}.db"))
        try:
            db.execute("BEGIN")
            step(db)
            db.execute(f"PRAGMA user_version = {number}")  # noqa: S608 - an int this module counts
            db.commit()
        except Exception:
            db.rollback()
            raise
        done.append(name)
    return done


__all__ = ["STEPS", "StoreTooNew", "latest", "upgrade", "version"]
