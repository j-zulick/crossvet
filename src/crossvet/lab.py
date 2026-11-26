"""The second local file: what Crossvet decided, what you rated, your notes, accepted routes and handoffs.

It is kept apart from the log of turns (store.py), keyed by the log's turn ids, so the log keeps its
schema and stays append-only. Path: ``CROSSVET_LAB_DB``, ``[lab] path``, else ``lab.db`` next to the log.
"""

from __future__ import annotations

import json
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any

from crossvet.store import connect

SCHEMA = """
CREATE TABLE IF NOT EXISTS decisions (turn_id INTEGER PRIMARY KEY, ts REAL NOT NULL, thread TEXT NOT NULL,
  asked TEXT NOT NULL, model TEXT NOT NULL, slot TEXT NOT NULL, goal TEXT NOT NULL, kind TEXT NOT NULL,
  difficulty INTEGER NOT NULL, reason TEXT NOT NULL, ladder TEXT NOT NULL, steps TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS decisions_thread ON decisions(thread, turn_id);
CREATE TABLE IF NOT EXISTS ratings (id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL NOT NULL, turn_id INTEGER NOT NULL,
  rating INTEGER NOT NULL, note TEXT NOT NULL DEFAULT '', source TEXT NOT NULL DEFAULT 'you');
CREATE INDEX IF NOT EXISTS ratings_turn ON ratings(turn_id);
CREATE TABLE IF NOT EXISTS notes (id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL NOT NULL, text TEXT NOT NULL,
  tags TEXT NOT NULL DEFAULT '');
CREATE TABLE IF NOT EXISTS routes (id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL NOT NULL, kind TEXT NOT NULL,
  model TEXT NOT NULL, previous TEXT NOT NULL DEFAULT '', evidence TEXT NOT NULL, status TEXT NOT NULL,
  decided REAL, origin TEXT NOT NULL DEFAULT 'ratings');
CREATE TABLE IF NOT EXISTS handoffs (id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL NOT NULL, agent TEXT NOT NULL,
  task TEXT NOT NULL, cwd TEXT NOT NULL, status TEXT NOT NULL, result TEXT NOT NULL DEFAULT '', seconds REAL);
CREATE TABLE IF NOT EXISTS kv (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS scores (id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL NOT NULL, turn_id INTEGER NOT NULL,
  model TEXT NOT NULL, kind TEXT NOT NULL, judge TEXT NOT NULL, score INTEGER, correct INTEGER NOT NULL DEFAULT 0,
  why TEXT NOT NULL DEFAULT '', cost REAL NOT NULL DEFAULT 0, shadow_of INTEGER);
CREATE INDEX IF NOT EXISTS scores_turn ON scores(turn_id);
CREATE TABLE IF NOT EXISTS reviews (id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL NOT NULL, author TEXT NOT NULL,
  reviewer TEXT NOT NULL, task TEXT NOT NULL, record TEXT NOT NULL);
"""
VERSION = 3


class Lab:
    """Decisions, ratings, notes, routes and handoffs in one SQLite file."""

    def __init__(self, path: str = ":memory:") -> None:  # noqa: D107
        if path != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self.lock = threading.RLock()  # shared by threads (handoffs, the server): see store.LockedDB
        self.db = connect(path, self.lock)
        self.db.executescript(SCHEMA)
        self.fts = True
        try:
            self.db.execute("CREATE VIRTUAL TABLE IF NOT EXISTS notes_fts USING fts5(text, tags, content='notes', content_rowid='id')")
        except sqlite3.OperationalError:  # an SQLite built without FTS5: search falls back to LIKE
            self.fts = False
        self.db.execute(f"PRAGMA user_version = {VERSION}")
        self.db.commit()

    # --- decisions ---

    def record_decision(self, turn_id: int, thread: str, asked: str, decision: dict[str, Any], steps: list[dict[str, Any]]) -> None:
        """Keep why a model was chosen and what each attempt did."""
        with self.lock:
            self.db.execute("INSERT OR REPLACE INTO decisions VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                            (turn_id, time.time(), thread, asked, decision["model"], decision["slot"], decision["goal"],
                             decision["kind"], decision["difficulty"], decision["reason"], json.dumps(decision["ladder"]),
                             json.dumps(steps)))
            self.db.commit()

    def decision(self, *, thread: str | None = None, turn_id: int | None = None) -> dict[str, Any] | None:
        """Return the decision for a turn, or the latest in a thread (or anywhere)."""
        with self.lock:
            if turn_id is not None:
                row = self.db.execute("SELECT * FROM decisions WHERE turn_id=?", (turn_id,)).fetchone()
            elif thread:
                row = self.db.execute("SELECT * FROM decisions WHERE thread=? ORDER BY turn_id DESC LIMIT 1", (thread,)).fetchone()
            else:
                row = self.db.execute("SELECT * FROM decisions ORDER BY turn_id DESC LIMIT 1").fetchone()
            if row is None:
                return None
            out = dict(row)
            out["ladder"], out["steps"] = json.loads(out["ladder"]), json.loads(out["steps"])
            return out

    def decisions(self, since: float = 0.0) -> list[dict[str, Any]]:
        """Return every decision since a time, oldest first."""
        with self.lock:
            rows = self.db.execute("SELECT * FROM decisions WHERE ts >= ? ORDER BY turn_id", (since,)).fetchall()
            return [{**dict(r), "ladder": json.loads(r["ladder"]), "steps": json.loads(r["steps"])} for r in rows]

    # --- ratings ---

    def rate(self, turn_id: int, rating: int, note: str = "", source: str = "you") -> int:
        """Record +1 (good) or -1 (bad) for a turn; return the rating's id."""
        with self.lock:
            if rating not in (1, -1):
                raise ValueError("a rating is +1 (good) or -1 (bad)")
            cur = self.db.execute("INSERT INTO ratings(ts, turn_id, rating, note, source) VALUES (?,?,?,?,?)",
                                  (time.time(), turn_id, rating, note[:2000], source))
            self.db.commit()
            return int(cur.lastrowid or 0)

    def ratings(self, since: float = 0.0) -> list[dict[str, Any]]:
        """Return the ratings since a time; the latest rating of a turn counts."""
        with self.lock:
            rows = self.db.execute("SELECT * FROM ratings WHERE id IN (SELECT MAX(id) FROM ratings GROUP BY turn_id) AND ts >= ? "
                                   "ORDER BY id", (since,)).fetchall()
            return [dict(r) for r in rows]

    # --- notes ---

    def save_note(self, text: str, tags: str = "") -> int:
        """Keep a note; return its id."""
        with self.lock:
            if not text.strip():
                raise ValueError("an empty note was not saved")
            cur = self.db.execute("INSERT INTO notes(ts, text, tags) VALUES (?,?,?)", (time.time(), text[:20000], tags[:200]))
            note_id = int(cur.lastrowid or 0)
            if self.fts:
                self.db.execute("INSERT INTO notes_fts(rowid, text, tags) VALUES (?,?,?)", (note_id, text[:20000], tags[:200]))
            self.db.commit()
            return note_id

    def search_notes(self, query: str, limit: int = 5) -> list[dict[str, Any]]:
        """Return the notes that match the words in ``query``, best first."""
        with self.lock:
            words = [w for w in "".join(c if c.isalnum() else " " for c in query).split() if len(w) > 1]
            if not words:
                rows = self.db.execute("SELECT * FROM notes ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
            elif self.fts:
                match = " OR ".join(f'"{w}"' for w in words)
                rows = self.db.execute("SELECT notes.* FROM notes_fts JOIN notes ON notes.id = notes_fts.rowid "
                                       "WHERE notes_fts MATCH ? ORDER BY rank LIMIT ?", (match, limit)).fetchall()
            else:
                clause = " OR ".join("text LIKE ?" for _ in words)
                rows = self.db.execute(f"SELECT * FROM notes WHERE {clause} ORDER BY id DESC LIMIT ?",  # noqa: S608
                                       (*[f"%{w}%" for w in words], limit)).fetchall()
            return [dict(r) for r in rows]

    # --- routes accepted with `crossvet tune` ---

    def propose_route(self, kind: str, model: str, previous: str, evidence: str, origin: str = "ratings") -> int:
        """Record a proposed route (kind -> model) unless the same one is already open."""
        with self.lock:
            row = self.db.execute("SELECT id FROM routes WHERE kind=? AND model=? AND status='proposed'", (kind, model)).fetchone()
            if row:
                return int(row["id"])
            cur = self.db.execute("INSERT INTO routes(ts, kind, model, previous, evidence, status, origin) VALUES (?,?,?,?,?,?,?)",
                                  (time.time(), kind, model, previous, evidence, "proposed", origin))
            self.db.commit()
            return int(cur.lastrowid or 0)

    def set_route_status(self, route_id: int, status: str) -> dict[str, Any]:
        """Accept, reject or roll back a route; accepting one closes the kind's earlier accepted route."""
        with self.lock:
            row = self.db.execute("SELECT * FROM routes WHERE id=?", (route_id,)).fetchone()
            if row is None:
                raise ValueError(f"no route #{route_id} (`crossvet tune` lists them)")
            allowed = {"accepted": ("proposed",), "rejected": ("proposed",), "rolled_back": ("accepted",)}
            if row["status"] not in allowed[status]:
                raise ValueError(f"route #{route_id} is {row['status']}; it can't become {status}")
            if status == "accepted":
                self.db.execute("UPDATE routes SET status='replaced', decided=? WHERE kind=? AND status='accepted'",
                                (time.time(), row["kind"]))
            self.db.execute("UPDATE routes SET status=?, decided=? WHERE id=?", (status, time.time(), route_id))
            self.db.commit()
            return dict(self.db.execute("SELECT * FROM routes WHERE id=?", (route_id,)).fetchone())

    def routes(self, status: str | None = None) -> list[dict[str, Any]]:
        """Return the routes, newest first, optionally of one status."""
        with self.lock:
            if status:
                rows = self.db.execute("SELECT * FROM routes WHERE status=? ORDER BY id DESC", (status,)).fetchall()
            else:
                rows = self.db.execute("SELECT * FROM routes ORDER BY id DESC").fetchall()
            return [dict(r) for r in rows]

    def pinned(self) -> dict[str, str]:
        """Return the accepted routes: kind -> model."""
        with self.lock:
            return {r["kind"]: r["model"] for r in self.routes("accepted")}

    # --- handoffs ---

    def add_handoff(self, agent: str, task: str, cwd: str) -> int:
        """Record a handoff as queued; return its id."""
        with self.lock:
            cur = self.db.execute("INSERT INTO handoffs(ts, agent, task, cwd, status) VALUES (?,?,?,?,?)",
                                  (time.time(), agent, task, cwd, "running"))
            self.db.commit()
            return int(cur.lastrowid or 0)

    def finish_handoff(self, handoff_id: int, status: str, result: str, seconds: float) -> None:
        """Record how a handoff ended."""
        with self.lock:
            self.db.execute("UPDATE handoffs SET status=?, result=?, seconds=? WHERE id=?", (status, result[:200_000], seconds, handoff_id))
            self.db.commit()

    def handoff(self, handoff_id: int) -> dict[str, Any] | None:
        """Return one handoff."""
        with self.lock:
            row = self.db.execute("SELECT * FROM handoffs WHERE id=?", (handoff_id,)).fetchone()
            return dict(row) if row else None

    # --- scores from the judge ---

    def add_score(self, turn_id: int, model: str, kind: str, judge: str, score: int | None, correct: bool, why: str,
                  cost: float, shadow_of: int | None = None) -> int:
        """Keep a judge's score for an answer (``score`` None = the judge's reply could not be read)."""
        cur = self.db.execute("INSERT INTO scores(ts, turn_id, model, kind, judge, score, correct, why, cost, shadow_of) "
                              "VALUES (?,?,?,?,?,?,?,?,?,?)",
                              (time.time(), turn_id, model, kind, judge, score, int(correct), why[:400], cost, shadow_of))
        self.db.commit()
        return int(cur.lastrowid or 0)

    # --- reviews ---

    def add_review(self, author: str, reviewer: str, task: str, record: dict[str, Any]) -> int:
        """Keep a review's decision record; return its id."""
        cur = self.db.execute("INSERT INTO reviews(ts, author, reviewer, task, record) VALUES (?,?,?,?,?)",
                              (time.time(), author, reviewer, task[:2000], json.dumps(record)))
        self.db.commit()
        return int(cur.lastrowid or 0)

    def reviews(self, limit: int = 20) -> list[dict[str, Any]]:
        """Return the latest reviews, newest first, with their records."""
        rows = self.db.execute("SELECT * FROM reviews ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
        return [{**dict(r), "record": json.loads(r["record"])} for r in rows]

    # --- small values (sync cursors and the like) ---

    def get(self, key: str, default: str = "") -> str:
        """Return a stored value."""
        with self.lock:
            row = self.db.execute("SELECT value FROM kv WHERE key=?", (key,)).fetchone()
            return str(row["value"]) if row else default

    def put(self, key: str, value: str) -> None:
        """Store a value."""
        with self.lock:
            self.db.execute("INSERT OR REPLACE INTO kv(key, value) VALUES (?,?)", (key, value))
            self.db.commit()
