"""The local log: one SQLite file with every turn (question and answer), its model, tokens and cost.

Turns are append-only (SQLite triggers refuse updates and deletes). A second table keeps OpenAI's
encrypted reasoning for tool calls for 7 days, so it can go back with the tool results (relay.py).
The file is safe to open from
the server, the MCP server and the terminal chat at once (WAL). It is the same file and table as
Crossvet 1.x, so earlier history carries over.
"""

from __future__ import annotations

import json
import sqlite3
import threading
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

SCHEMA = """
CREATE TABLE IF NOT EXISTS turns (
  id INTEGER PRIMARY KEY AUTOINCREMENT, thread TEXT NOT NULL, ts REAL NOT NULL, author TEXT NOT NULL,
  role TEXT NOT NULL, model TEXT NOT NULL DEFAULT '', content TEXT NOT NULL, cost REAL, meta TEXT NOT NULL DEFAULT '{}');
CREATE INDEX IF NOT EXISTS turns_thread ON turns(thread, id);
CREATE TABLE IF NOT EXISTS store (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TRIGGER IF NOT EXISTS turns_no_update BEFORE UPDATE ON turns BEGIN SELECT RAISE(ABORT, 'turns are append-only'); END;
CREATE TRIGGER IF NOT EXISTS turns_no_delete BEFORE DELETE ON turns BEGIN SELECT RAISE(ABORT, 'turns are append-only'); END;
CREATE TABLE IF NOT EXISTS relay_state (call_id TEXT PRIMARY KEY, ts REAL NOT NULL, model TEXT NOT NULL, items TEXT NOT NULL);
"""
STATE_DAYS = 7  # kept reasoning older than this is dropped
VERSION = 1  # SQLite user_version this release writes and reads


class Result:
    """A query's rows, read in full while the lock was held, with the cursor's row count and last row id."""

    def __init__(self, rows: list[sqlite3.Row], rowcount: int, lastrowid: int | None) -> None:  # noqa: D107
        self.rows, self.rowcount, self.lastrowid = rows, rowcount, lastrowid

    def fetchall(self) -> list[sqlite3.Row]:
        """Return every row."""
        return self.rows

    def fetchone(self) -> sqlite3.Row | None:
        """Return the first row, or ``None``."""
        return self.rows[0] if self.rows else None


class LockedDB:
    """A SQLite connection shared by threads: each statement runs and is read in full under one lock.

    sqlite3 reuses one prepared statement for the same SQL text, so two threads running the same
    query on one connection (the server's thread pool, or compare's parallel calls) can reset each
    other's statement and get no row back. Reading every result inside the lock prevents that.
    """

    def __init__(self, connection: sqlite3.Connection, lock: threading.RLock) -> None:  # noqa: D107
        self.connection, self.lock = connection, lock

    def execute(self, sql: str, params: Any = ()) -> Result:
        """Run one statement and read all of its rows."""
        with self.lock:
            cursor = self.connection.execute(sql, params)
            return Result(cursor.fetchall(), cursor.rowcount, cursor.lastrowid)

    def executemany(self, sql: str, params: Any) -> Result:
        """Run one statement for each set of parameters."""
        with self.lock:
            cursor = self.connection.executemany(sql, params)
            return Result([], cursor.rowcount, cursor.lastrowid)

    def executescript(self, script: str) -> None:
        """Run several statements."""
        with self.lock:
            self.connection.executescript(script)

    def commit(self) -> None:
        """Commit."""
        with self.lock:
            self.connection.commit()

    def backup(self, target: Any) -> None:
        """Copy this database into ``target`` (a connection or a :class:`LockedDB`)."""
        with self.lock:
            self.connection.backup(target.connection if isinstance(target, LockedDB) else target)

    def close(self) -> None:
        """Close the connection."""
        with self.lock:
            self.connection.close()

    def __enter__(self) -> LockedDB:  # noqa: D105
        self.lock.acquire()
        self.connection.__enter__()
        return self

    def __exit__(self, *exc: Any) -> None:  # noqa: D105
        try:
            self.connection.__exit__(*exc)
        finally:
            self.lock.release()


def connect(path: str, lock: threading.RLock) -> LockedDB:
    """Open a SQLite file for use from several threads (WAL unless in memory)."""
    connection = sqlite3.connect(path, timeout=10, check_same_thread=False)
    connection.row_factory = sqlite3.Row
    if path != ":memory:":
        connection.execute("PRAGMA journal_mode=WAL")
    return LockedDB(connection, lock)


class StoreTooNew(RuntimeError):
    """The log was written by a newer Crossvet than this one."""


@dataclass
class Turn:
    """One message in a thread."""

    id: int
    thread: str
    ts: float
    author: str     # the app that sent it: api, mcp, terminal...
    role: str       # user or assistant
    model: str
    content: str
    cost: float | None
    meta: dict[str, Any]


def new_thread() -> str:
    """Return a fresh thread id."""
    return uuid.uuid4().hex[:12]


class Store:
    """The local log of turns."""

    def __init__(self, path: str = ":memory:") -> None:  # noqa: D107
        if path != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        # One connection is shared by the server's threads and by compare's parallel calls. sqlite3 reuses one prepared
        # statement for the same SQL, so two threads running it at once can reset each other: every query holds this lock.
        self.lock = threading.RLock()
        self.db = connect(path, self.lock)
        version = int(self.db.execute("PRAGMA user_version").fetchone()[0])
        if version > VERSION:
            raise StoreTooNew(f"{path} is schema version {version}, written by a newer Crossvet (this one reads "
                              f"{VERSION}); update Crossvet, or set CROSSVET_DB to another file")
        self.db.executescript(SCHEMA)
        if version == 0:
            self.db.execute(f"PRAGMA user_version = {VERSION}")
        self.db.commit()

    def add_turn(self, thread: str, author: str, role: str, content: str, model: str = "",
                 cost: float | None = None, meta: dict[str, Any] | None = None) -> int:
        """Append one message to a thread; return its id."""
        with self.lock:
            cur = self.db.execute(
                "INSERT INTO turns(thread, ts, author, role, model, content, cost, meta) VALUES (?,?,?,?,?,?,?,?)",
                (thread, time.time(), author, role, model, content, cost, json.dumps(meta or {})))
            self.db.commit()
            return int(cur.lastrowid or 0)

    def turns(self, thread: str, limit: int = 50) -> list[Turn]:
        """Return the last ``limit`` turns of a thread, oldest first."""
        with self.lock:
            rows = self.db.execute("SELECT * FROM turns WHERE thread=? ORDER BY id DESC LIMIT ?", (thread, limit)).fetchall()
            return [_turn(r) for r in reversed(rows)]

    def recent(self, limit: int = 20) -> list[Turn]:
        """Return the last ``limit`` turns across every app, newest first."""
        with self.lock:
            return [_turn(r) for r in self.db.execute("SELECT * FROM turns ORDER BY id DESC LIMIT ?", (limit,)).fetchall()]

    def save_state(self, model: str, state: dict[str, Any]) -> None:
        """Keep the reasoning behind each tool call (tool-call id -> items); drop entries older than a week."""
        with self.lock:
            now = time.time()
            self.db.execute("DELETE FROM relay_state WHERE ts < ?", (now - STATE_DAYS * 86400,))
            self.db.executemany("INSERT OR REPLACE INTO relay_state(call_id, ts, model, items) VALUES (?,?,?,?)",
                                [(call_id, now, model, json.dumps(items)) for call_id, items in state.items()])
            self.db.commit()

    def load_state(self, model: str, call_ids: list[str]) -> dict[str, Any]:
        """Return the kept reasoning for these tool-call ids, from the same model only."""
        with self.lock:
            if not call_ids:
                return {}
            marks = ",".join("?" * len(call_ids))
            rows = self.db.execute(f"SELECT call_id, items FROM relay_state WHERE model=? AND call_id IN ({marks})",  # noqa: S608
                                   (model, *call_ids)).fetchall()
            return {r["call_id"]: json.loads(r["items"]) for r in rows}

    def spent_today(self) -> float:
        """USD recorded on turns since local midnight."""
        with self.lock:
            midnight = time.mktime(time.localtime()[:3] + (0, 0, 0, 0, 0, -1))
            row = self.db.execute("SELECT COALESCE(SUM(cost), 0) s FROM turns WHERE ts >= ?", (midnight,)).fetchone()
            return float(row["s"])

    def spending(self, *, since: float = 0.0, thread: str | None = None) -> dict[str, dict[str, float]]:
        """Answers and USD per model: ``{model: {"answers", "usd", "unpriced"}}`` (unpriced = answers with no cost)."""
        with self.lock:
            sql = ("SELECT model, COUNT(*) n, COALESCE(SUM(cost), 0) usd, SUM(cost IS NULL) unpriced FROM turns "
                   "WHERE role='assistant' AND ts >= ?")
            params: list[Any] = [since]
            if thread:
                sql += " AND thread = ?"
                params.append(thread)
            rows = self.db.execute(sql + " GROUP BY model ORDER BY usd DESC", params).fetchall()
            return {r["model"]: {"answers": r["n"], "usd": r["usd"], "unpriced": r["unpriced"] or 0} for r in rows}


def _turn(r: sqlite3.Row) -> Turn:
    return Turn(r["id"], r["thread"], r["ts"], r["author"], r["role"], r["model"], r["content"], r["cost"],
                json.loads(r["meta"] or "{}"))
