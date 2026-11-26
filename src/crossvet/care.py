"""Look after the two local files: export, report, a dashboard page, backup, restore and prune.

    crossvet export [--out FILE]           every answer as JSON lines, with its decision and rating
    crossvet report [--days 7]             spend, answers per kind and slot, escalations and ratings, in Markdown
    crossvet dashboard [--out FILE]        the same numbers as one self-contained HTML page
    crossvet backup DIR                    consistent copies of the log and the lab file, with SHA-256 sums
    crossvet restore DIR [--force]         checks the sums, then puts the copies back
    crossvet prune [--days 30]             drops kept tool-call reasoning and finished handoffs older than N days

The log of turns is append-only, so prune never removes a turn: it only frees the side tables.
"""

from __future__ import annotations

import hashlib
import html
import json
import sqlite3
import time
from collections import Counter, defaultdict
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from crossvet.core import Crossvet

FILES = ("chat.db", "lab.db")


def rows(cv: Crossvet, since: float = 0.0) -> list[dict[str, Any]]:
    """Return every answer since a time, oldest first, with its question, decision and latest rating."""
    ratings = {r["turn_id"]: r for r in cv.lab.ratings()}
    out = []
    for row in cv.store.db.execute("SELECT a.*, q.content question FROM turns a LEFT JOIN turns q ON q.thread = a.thread "
                                   "AND q.id = a.id - 1 AND q.role = 'user' WHERE a.role = 'assistant' AND a.ts >= ? "
                                   "ORDER BY a.id", (since,)).fetchall():
        rating = ratings.get(row["id"])
        out.append({"turn": row["id"], "ts": row["ts"], "thread": row["thread"], "app": row["author"], "model": row["model"],
                    "question": row["question"] or "", "answer": row["content"], "cost": row["cost"],
                    "meta": json.loads(row["meta"] or "{}"), "decision": cv.lab.decision(turn_id=row["id"]),
                    "rating": rating["rating"] if rating else None})
    return out


def export(cv: Crossvet, out: Path | None = None, since: float = 0.0) -> str:
    """Return (or write) every answer as JSON lines."""
    text = "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows(cv, since))
    if out:
        out.write_text(text)
        return f"wrote {text.count(chr(10))} answers to {out}"
    return text


def summary(cv: Crossvet, days: float = 7) -> dict[str, Any]:
    """Return the numbers the report and the dashboard show."""
    since = time.time() - days * 86400 if days else 0.0
    data = rows(cv, since)
    per_model: dict[str, dict[str, float]] = defaultdict(lambda: {"answers": 0, "usd": 0.0, "good": 0, "bad": 0})
    for r in data:
        cell = per_model[r["model"]]
        cell["answers"] += 1
        cell["usd"] += r["cost"] or 0.0
        if r["rating"] == 1:
            cell["good"] += 1
        elif r["rating"] == -1:
            cell["bad"] += 1
    chosen = [r for r in data if r["decision"]]
    escalated = [r for r in chosen if len(r["decision"]["steps"]) > 1]
    return {"days": days, "answers": len(data), "usd": round(sum(r["cost"] or 0 for r in data), 6),
            "per_model": {k: dict(v) for k, v in sorted(per_model.items(), key=lambda kv: -kv[1]["answers"])},
            "apps": dict(Counter(r["app"] for r in data).most_common()),
            "kinds": dict(Counter(r["decision"]["kind"] for r in chosen).most_common()),
            "slots": dict(Counter(r["decision"]["slot"] for r in chosen).most_common()),
            "chosen": len(chosen), "escalated": len(escalated),
            "rated": sum(1 for r in data if r["rating"] is not None)}


def report(cv: Crossvet, days: float = 7) -> str:
    """Return the report in Markdown, every number computed from the local files."""
    s = summary(cv, days)
    span = f"the last {days:g} days" if days else "all time"
    lines = [f"# Crossvet report: {span}", "", f"Generated {time.strftime('%Y-%m-%d %H:%M')} from the local log.", "",
             f"- Answers: {s['answers']} (Crossvet chose the model for {s['chosen']}; {s['escalated']} needed a second model)",
             f"- Spend: ${s['usd']:.4f}", f"- Rated: {s['rated']}", "", "## Per model", "",
             "| Model | Answers | Spend | Rated good | Rated bad |", "|---|---:|---:|---:|---:|"]
    lines += [f"| `{m}` | {int(c['answers'])} | ${c['usd']:.4f} | {int(c['good'])} | {int(c['bad'])} |" for m, c in s["per_model"].items()]
    for title, key in (("Apps", "apps"), ("Kinds of task (auto only)", "kinds"), ("Slots (auto only)", "slots")):
        lines += ["", f"## {title}", ""] + ([f"- {k}: {v}" for k, v in s[key].items()] or ["- none"])
    return "\n".join(lines) + "\n"


def dashboard(cv: Crossvet, days: float = 7) -> str:
    """Return a self-contained HTML page with the report's numbers (no scripts, no outside files)."""
    s = summary(cv, days)
    top = max([c["answers"] for c in s["per_model"].values()] or [1])
    bars = "".join(
        f"<tr><td><code>{html.escape(m)}</code></td><td><div class=bar style='width:{100 * c['answers'] / top:.0f}%'></div>"
        f"{int(c['answers'])}</td><td>${c['usd']:.4f}</td><td>{int(c['good'])} / {int(c['good'] + c['bad'])}</td></tr>"
        for m, c in s["per_model"].items())
    lists = "".join(f"<h2>{t}</h2><ul>" + ("".join(f"<li>{html.escape(str(k))}: {v}</li>" for k, v in s[key].items()) or "<li>none</li>")
                    + "</ul>" for t, key in (("Apps", "apps"), ("Kinds of task", "kinds"), ("Slots", "slots")))
    span = f"last {days:g} days" if days else "all time"
    return f"""<!doctype html><html lang=en><meta charset=utf-8><title>Crossvet: {span}</title>
<style>body{{font:15px/1.5 system-ui,sans-serif;max-width:860px;margin:2rem auto;padding:0 1rem;color:#1d1d1f}}
table{{border-collapse:collapse;width:100%}}td,th{{padding:.4rem;border-bottom:1px solid #e5e5e5;text-align:left}}
.bar{{display:inline-block;height:.7rem;background:#4f6bed;margin-right:.4rem;border-radius:3px}}
.k{{display:flex;gap:2rem}}.k b{{font-size:1.6rem;display:block}}</style>
<h1>Crossvet, {span}</h1><div class=k><div><b>{s['answers']}</b>answers</div><div><b>${s['usd']:.4f}</b>spend</div>
<div><b>{s['chosen']}</b>chosen by auto</div><div><b>{s['escalated']}</b>escalated</div><div><b>{s['rated']}</b>rated</div></div>
<h2>Per model</h2><table><tr><th>Model</th><th>Answers</th><th>Spend</th><th>Rated good</th></tr>{bars}</table>{lists}
<p><small>Generated {time.strftime('%Y-%m-%d %H:%M')} from the local files.</small></p></html>
"""


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def backup(cv: Crossvet, folder: Path) -> str:
    """Write consistent copies of the log and the lab file, and their SHA-256 sums, into ``folder``."""
    folder.mkdir(parents=True, exist_ok=True)
    sums = {}
    for name, db in zip(FILES, (cv.store.db, cv.lab.db), strict=True):
        target = folder / name
        if target.exists():
            target.unlink()
        copy = sqlite3.connect(target)
        db.backup(copy)
        copy.close()
        sums[name] = _sha(target)
    (folder / "SHA256SUMS").write_text("".join(f"{h}  {n}\n" for n, h in sums.items()))
    turns = cv.store.db.execute("SELECT COUNT(*) FROM turns").fetchone()[0]
    return f"backed up {turns} turns and the lab file to {folder} (SHA256SUMS written)"


def restore(cv: Crossvet, folder: Path, force: bool = False) -> str:
    """Check the sums in ``folder``, then copy the backup over the log and the lab file."""
    sums_file = folder / "SHA256SUMS"
    if not sums_file.is_file():
        raise ValueError(f"{folder} has no SHA256SUMS: it is not a Crossvet backup")
    sums = dict(reversed(line.split("  ", 1)) for line in sums_file.read_text().splitlines() if line.strip())
    for name in FILES:
        if name not in sums or not (folder / name).is_file() or _sha(folder / name) != sums[name]:
            raise ValueError(f"{name} in {folder} is missing or does not match its SHA-256 sum; nothing was restored")
    if cv.store.path == ":memory:":
        raise ValueError("this Crossvet has no log file to restore into")
    turns = cv.store.db.execute("SELECT COUNT(*) FROM turns").fetchone()[0]
    if turns and not force:
        raise ValueError(f"the log has {turns} turns; add --force to replace it with the backup")
    for name, db in zip(FILES, (cv.store.db, cv.lab.db), strict=True):
        source = sqlite3.connect(folder / name)
        with db.lock:
            source.backup(db.connection)  # replaces the whole file, triggers included
        source.close()
    from crossvet.store import SCHEMA

    cv.store.db.executescript(SCHEMA)  # puts the append-only triggers back
    restored = cv.store.db.execute("SELECT COUNT(*) FROM turns").fetchone()[0]
    return f"restored {restored} turns and the lab file from {folder}"


def prune(cv: Crossvet, days: float = 30) -> str:
    """Drop kept tool-call reasoning and finished handoffs older than ``days``; turns are never removed."""
    cutoff = time.time() - days * 86400
    state = cv.store.db.execute("DELETE FROM relay_state WHERE ts < ?", (cutoff,)).rowcount
    cv.store.db.commit()
    handoffs = cv.lab.db.execute("DELETE FROM handoffs WHERE ts < ? AND status != 'running'", (cutoff,)).rowcount
    cv.lab.db.commit()
    for db in (cv.store.db, cv.lab.db):
        db.execute("VACUUM")
    return f"removed {state} kept reasoning item(s) and {handoffs} finished handoff(s) older than {days:g} days; turns are kept"
