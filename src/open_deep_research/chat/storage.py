"""Back up, restore and prune the chat store (one SQLite file).

- ``backup`` copies the store with SQLite's online backup, so it is consistent even while the
  server writes, then checks the copy.
- ``restore`` checks a backup, saves the current store next to it first, then copies the backup in.
- ``prune`` keeps the turns of the last N days. The store refuses deletes by design, so pruning
  builds a new file with the rows to keep and puts it in place of the old one, after saving a
  backup. Notes, the routing table and its evidence, and handoffs are all kept; ratings are kept
  for the turns that remain. The store keeps its id, so Langfuse trace ids still match.

Stop ``crossvet chat serve`` / ``start`` and any MCP server before ``restore`` or ``prune``: a
process that keeps the old file open would go on writing to it.
"""

from __future__ import annotations

import os
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path

REQUIRED = ("turns", "feedback", "notes", "store")
PRUNED = ("turns", "feedback")  # every other table is kept whole


def counts(db: sqlite3.Connection) -> dict[str, int]:
    """Return the rows in the tables people care about."""
    out = {}
    for table, label in (("turns", "turns"), ("notes", "notes"), ("feedback", "ratings")):
        try:
            out[label] = int(db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])  # noqa: S608 - fixed names
        except sqlite3.OperationalError:
            out[label] = 0
    return out


def problems(path: str | Path) -> list[str]:
    """Return what is wrong with a store file ("" list when it is a readable Crossvet chat store)."""
    path = Path(path)
    if not path.is_file():
        return [f"{path} does not exist"]
    try:
        db = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        try:
            check = db.execute("PRAGMA integrity_check").fetchone()[0]
            tables = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            store_id = db.execute("SELECT value FROM store WHERE key='id'").fetchone() if "store" in tables else None
        finally:
            db.close()
    except sqlite3.DatabaseError as exc:
        return [f"{path} is not a SQLite database ({exc})"]
    out = [] if check == "ok" else [f"integrity check: {check}"]
    missing = [t for t in REQUIRED if t not in tables]
    if missing:
        out.append(f"not a Crossvet chat store (missing {', '.join(missing)})")
    elif store_id is None:
        out.append("the store has no id")
    return out


def _stamp() -> str:
    return time.strftime("%Y%m%d-%H%M%S")


def backup(db_path: str | Path, dest: str | Path | None = None) -> tuple[Path, dict[str, int]]:
    """Copy the store to ``dest`` (default: ``crossvet-chat-backup-<time>.db`` here); return the path and row counts."""
    source = Path(db_path)
    if not source.is_file():
        raise FileNotFoundError(f"there is no chat store at {source}")
    target = Path(dest) if dest else Path(f"crossvet-chat-backup-{_stamp()}.db")
    if target.exists():
        raise FileExistsError(f"{target} already exists")
    target.parent.mkdir(parents=True, exist_ok=True)
    src = sqlite3.connect(source)
    dst = sqlite3.connect(target)
    try:
        src.backup(dst)
        found = counts(dst)
    finally:
        dst.close()
        src.close()
    wrong = problems(target)
    if wrong:
        raise RuntimeError(f"the backup at {target} did not check out: {'; '.join(wrong)}")
    return target, found


def restore(backup_path: str | Path, db_path: str | Path) -> tuple[Path | None, dict[str, int]]:
    """Replace the store with a backup; return where the previous store was saved and the restored counts."""
    wrong = problems(backup_path)
    if wrong:
        raise RuntimeError(f"not restoring {backup_path}: {'; '.join(wrong)}")
    target = Path(db_path)
    saved = None
    if target.is_file():
        saved, _ = backup(target, target.with_name(f"{target.stem}.before-restore-{_stamp()}.db"))
    target.parent.mkdir(parents=True, exist_ok=True)
    src = sqlite3.connect(f"file:{backup_path}?mode=ro", uri=True)
    dst = sqlite3.connect(target)
    try:
        src.backup(dst)  # SQLite writes it through the live file's own journal, WAL included
        found = counts(dst)
    finally:
        dst.close()
        src.close()
    return saved, found


@dataclass
class PruneResult:
    """What a prune kept and removed."""

    kept_turns: int
    removed_turns: int
    removed_ratings: int
    backup: Path


def prune(db_path: str | Path, older_than_days: float, now: float | None = None,
          backup_to: str | Path | None = None) -> PruneResult:
    """Keep turns from the last ``older_than_days`` days (and their ratings); keep everything else."""
    from open_deep_research.chat.handoff import Queue
    from open_deep_research.chat.memory import Memory
    from open_deep_research.chat.tuning import Tuning

    if older_than_days <= 0:
        raise ValueError("--older-than must be more than 0 days")
    target = Path(db_path)
    wrong = problems(target)
    if wrong:
        raise RuntimeError(f"not pruning {target}: {'; '.join(wrong)}")
    saved, before = backup(target, backup_to or target.with_name(f"{target.stem}.before-prune-{_stamp()}.db"))
    cutoff = (now or time.time()) - older_than_days * 86400
    building = target.with_name(target.name + ".pruning")
    for leftover in (building, Path(f"{building}-wal"), Path(f"{building}-shm")):
        leftover.unlink(missing_ok=True)
    fresh = Memory(str(building))  # the current schema, search index and triggers
    Tuning(fresh.db)
    Queue(fresh.db)
    db = fresh.db
    db.execute("ATTACH DATABASE ? AS old", (str(target),))
    store_id = db.execute("SELECT value FROM old.store WHERE key='id'").fetchone()[0]
    db.execute("DELETE FROM main.store")
    db.execute("INSERT INTO main.store(key, value) SELECT key, value FROM old.store")
    new_tables = {r[0] for r in db.execute("SELECT name FROM main.sqlite_master WHERE type='table'")}
    old_tables = {r[0] for r in db.execute("SELECT name FROM old.sqlite_master WHERE type='table'")}
    skip = {"store", "sqlite_sequence"} | {t for t in new_tables if t.endswith(("_fts", "_config", "_data", "_docsize", "_idx"))}
    for table in ["turns", "feedback"] + sorted((new_tables & old_tables) - skip - set(PRUNED)):
        if table not in old_tables or table not in new_tables:
            continue
        old_cols = {r[1] for r in db.execute(f"PRAGMA old.table_info({table})")}
        cols = [r[1] for r in db.execute(f"PRAGMA main.table_info({table})") if r[1] in old_cols]
        names = ", ".join(cols)
        where = {"turns": "WHERE ts >= ?", "feedback": "WHERE turn_id IN (SELECT id FROM main.turns)"}.get(table, "")
        params = (cutoff,) if table == "turns" else ()
        db.execute(f"INSERT INTO main.{table}({names}) SELECT {names} FROM old.{table} {where}", params)  # noqa: S608
    db.commit()
    after = counts(db)
    db.execute("DETACH DATABASE old")
    check = db.execute("PRAGMA integrity_check").fetchone()[0]
    if db.execute("SELECT value FROM store WHERE key='id'").fetchone()[0] != store_id:
        check = "the store id changed"
    db.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    db.close()
    if check != "ok":
        raise RuntimeError(f"the pruned copy failed its integrity check ({check}); the store was not changed")
    old = sqlite3.connect(target)
    old.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    old.close()
    os.replace(building, target)
    for side in (Path(f"{target}-wal"), Path(f"{target}-shm"), Path(f"{building}-wal"), Path(f"{building}-shm")):
        side.unlink(missing_ok=True)
    return PruneResult(after["turns"], before["turns"] - after["turns"], before["ratings"] - after["ratings"], saved)
