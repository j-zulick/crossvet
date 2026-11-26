"""The review benchmark: does a reviewer catch a bug planted in a real change?

Each case is a small change to Crossvet's own code (the functions are the real ones from this
repository) with one bug planted on a known line: an off-by-one, a wrong unit, SQL built from text,
a key written to a log, an inverted check, a missing ``await``, a cap that never stops, a mutable
default, a swallowed error, the wrong price, a comparison that leaks timing, a cap counted the
wrong way round. Scoring is code: a reviewer catches the bug when one of its findings that passed
``review.check`` points at the planted line (one line either side counts). Findings elsewhere are
counted as "other findings"; they are not graded.

    crossvet bench --review -m sol -m opus           every case, each reviewer, a results page
    crossvet bench --review --set hard -m sol        subtler bugs, plus clean changes that should get no blocker

The ``hard`` set plants bugs that read like reasonable code (a ladder cut one model short, an
exploration test turned round, a lock released before the rows are read, a week written in
seconds), and adds clean changes with no bug at all. A blocker or major finding on a clean change
is a false alarm; that is the number the planted set cannot show.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from crossvet.providers import ProviderError

if TYPE_CHECKING:
    from crossvet.core import Crossvet

NEAR = 1
ALARM = ("blocker", "major")  # on a clean change, a kept finding with one of these severities is a false alarm


@dataclass(frozen=True)
class Planted:
    """A change with one planted bug, or a clean change (``bug`` is ``None``)."""

    name: str
    kind: str
    task: str
    path: str
    start: int                 # new-side line number of the first context line
    before: tuple[str, ...]    # context lines before the change
    removed: tuple[str, ...]   # lines the change takes out
    added: tuple[str, ...]     # lines the change puts in; one holds the bug
    bug: int | None            # index into ``added`` of the planted bug; ``None`` for a clean change
    after: tuple[str, ...] = ()

    @property
    def clean(self) -> bool:
        """Return whether the change has no planted bug."""
        return self.bug is None

    @property
    def line(self) -> int:
        """Return the planted bug's line number on the new side (0 for a clean change)."""
        return 0 if self.bug is None else self.start + len(self.before) + self.bug

    def diff(self) -> str:
        """Return the change as a unified diff."""
        old = len(self.before) + len(self.removed) + len(self.after)
        new = len(self.before) + len(self.added) + len(self.after)
        body = [f" {x}" for x in self.before] + [f"-{x}" for x in self.removed] + [f"+{x}" for x in self.added] + [f" {x}" for x in self.after]
        return (f"diff --git a/{self.path} b/{self.path}\n--- a/{self.path}\n+++ b/{self.path}\n"
                f"@@ -{self.start},{old} +{self.start},{new} @@\n" + "\n".join(body) + "\n")


CASES: tuple[Planted, ...] = (
    Planted("turns-limit", "off-by-one", "Return the last `limit` turns of a thread, oldest first.", "src/crossvet/store.py", 96,
            ('    def turns(self, thread: str, limit: int = 50) -> list[Turn]:', '        """Return the last ``limit`` turns of a thread, oldest first."""'),
            ('        rows = self.db.execute("SELECT * FROM turns WHERE thread=? ORDER BY id DESC LIMIT ?", (thread, limit)).fetchall()',),
            ('        rows = self.db.execute("SELECT * FROM turns WHERE thread=? ORDER BY id DESC LIMIT ?", (thread, limit - 1)).fetchall()',), 0,
            ('        return [_turn(r) for r in reversed(rows)]',)),
    Planted("timeout-unit", "wrong unit", "Set how long one model call may take, from [limits] timeout_seconds.", "src/crossvet/providers.py", 45,
            ('def set_timeout(seconds: float) -> None:', '    """Set how long one model call may take (``[limits] timeout_seconds``)."""', '    global TIMEOUT  # noqa: PLW0603'),
            ('    TIMEOUT = httpx.Timeout(float(seconds), connect=min(10.0, float(seconds)))',),
            ('    TIMEOUT = httpx.Timeout(float(seconds) / 1000, connect=min(10.0, float(seconds)))',), 0),
    Planted("thread-sql", "SQL injection", "Let recent_turns filter by thread id.", "src/crossvet/store.py", 104,
            ('    def recent(self, limit: int = 20, thread: str = "") -> list[Turn]:', '        """Return the last ``limit`` turns, newest first, optionally of one thread."""'),
            ('        return [_turn(r) for r in self.db.execute("SELECT * FROM turns ORDER BY id DESC LIMIT ?", (limit,)).fetchall()]',),
            ('        where = f"WHERE thread = \'{thread}\'" if thread else ""',
             '        return [_turn(r) for r in self.db.execute(f"SELECT * FROM turns {where} ORDER BY id DESC LIMIT ?", (limit,)).fetchall()]'), 0),
    Planted("key-in-log", "secret leak", "Log each outgoing call to help debugging.", "src/crossvet/providers.py", 118,
            ('def _post(url: str, headers: dict[str, str], body: dict[str, Any], transport: httpx.BaseTransport | None) -> dict[str, Any]:',
             '    host = httpx.URL(url).host'),
            (),
            ('    logging.getLogger("crossvet").info("POST %s headers=%s", url, headers)',), 0,
            ('    try:',)),
    Planted("token-check", "auth bypass", "Accept the bearer token from the Authorization header.", "src/crossvet/server.py", 140,
            ('    def allowed(request: Request) -> bool:', '        if not token:', '            return True'),
            ('        sent = request.headers.get("authorization", "").removeprefix("Bearer ").strip()',
             '        return hmac.compare_digest(sent.encode(), token.encode())'),
            ('        sent = request.headers.get("authorization", "").removeprefix("Bearer ").strip()',
             '        return bool(sent) or hmac.compare_digest(sent.encode(), token.encode())'), 1),
    Planted("missing-await", "async", "Slow down token guessing with a pause before answering 401.", "src/crossvet/server.py", 152,
            ('    async def denied() -> JSONResponse:',),
            ('        await asyncio.sleep(FAIL_DELAY_SECONDS)  # slows guessing',),
            ('        asyncio.sleep(FAIL_DELAY_SECONDS)  # slows guessing',), 0,
            ('        return error(401, "missing or wrong token", "authentication_error")',)),
    Planted("daily-cap", "comparison", "Stop calls once today's spend reaches the daily cap.", "src/crossvet/core.py", 112,
            ('        cfg = self.config', '        if cfg.max_usd_per_day > 0:', '            spent = self.store.spent_today()'),
            ('            if spent >= cfg.max_usd_per_day:',),
            ('            if spent > cfg.max_usd_per_day * 2:',), 0,
            ('                raise BudgetExceeded(f"the daily cap is reached: ${spent:.2f} of ${cfg.max_usd_per_day:.2f}")',)),
    Planted("mutable-default", "mutable default", "Let callers pass extra metadata for a turn.", "src/crossvet/store.py", 84,
            (),
            ('    def add_turn(self, thread: str, author: str, role: str, content: str, model: str = "",',
             '                 cost: float | None = None, meta: dict[str, Any] | None = None) -> int:'),
            ('    def add_turn(self, thread: str, author: str, role: str, content: str, model: str = "",',
             '                 cost: float | None = None, meta: dict[str, Any] = {}) -> int:',
             '        meta.setdefault("logged_at", time.time())'), 1,
            ('        """Append one message to a thread; return its id."""',)),
    Planted("swallowed-refusal", "error handling", "Make streaming failures easier to read.", "src/crossvet/core.py", 160,
            ('        try:', '            for item in self.streamer(model, messages, self.config.max_output_tokens):', '                yield item'),
            ('        except AccountError:', '            self._refusal(model)', '            raise'),
            ('        except AccountError:', '            pass'), 1),
    Planted("input-price", "wrong value", "Price a call from its tokens.", "src/crossvet/config.py", 88,
            ('    def cost(self, model: str, input_tokens: int, output_tokens: int) -> float | None:',
             '        """List-price cost of a call, or ``None`` when the model has no price."""', '        price = self.price(model)'),
            ('        return None if price is None else (input_tokens * price[0] + output_tokens * price[1]) / 1_000_000',),
            ('        return None if price is None else (input_tokens * price[1] + output_tokens * price[1]) / 1_000_000',), 0),
    Planted("token-timing", "timing leak", "Compare the token the client sent with the configured one.", "src/crossvet/server.py", 143,
            ('        sent = request.headers.get("authorization", "").removeprefix("Bearer ").strip()',),
            ('        return hmac.compare_digest(sent.encode(), token.encode())',),
            ('        return sent == token',), 0),
    Planted("refused-forever", "logic", "Remember providers that refused the account.", "src/crossvet/core.py", 108,
            ('        provider = providers.split(model)[0]',),
            ('        if provider in self.refused:',),
            ('        if provider not in self.refused:',), 0,
            ('            raise AccountError(f"{provider} refused your key earlier in this run")',)),
)

HARD: tuple[Planted, ...] = (
    Planted("ladder-trim", "off-by-one", "Keep only the models escalation would try: the first model plus up to max_steps more.",
            "src/crossvet/routing.py", 213,
            ('        if not ladder:',
             '            raise ValueError("auto found no model it can call: add an API key (`crossvet doctor` shows which are set) "',
             '                             "or fill [slots] in crossvet.toml")'),
            ('    ladder = ladder[: 1 + (cfg.max_steps if cfg.escalate else 0)]  # only the models escalation would try',),
            ('    ladder = ladder[: cfg.max_steps if cfg.escalate else 1]  # only the models escalation would try',), 0,
            ('    return Decision(model=ladder[0], slot=slot, goal=goal, kind=task.kind, difficulty=task.difficulty, reason=why,',)),
    Planted("explore-flip", "inverted test", "Send about `explore` of requests (5% by default) to the second choice by score.",
            "src/crossvet/routing.py", 156,
            ('    top = cells[ranked[0]]',
             '    why = (f"scores: {ranked[0]} is the cheapest within {cfg.margin:g} of the best cautious score for {kind} "',
             '           f"({top[\'low\']:.2f}, n={int(top[\'n\'])}; best {best:.2f})")'),
            ('    if len(ranked) > 1 and (rng or random).random() < cfg.explore:',),
            ('    if len(ranked) > 1 and (rng or random).random() > cfg.explore:',), 0,
            ('        ranked[0], ranked[1] = ranked[1], ranked[0]',)),
    Planted("private-scores", "privacy", "Tidy the condition for when scores rank models; behaviour should not change.",
            "src/crossvet/routing.py", 196,
            ('    scored: list[str] = []',),
            ('    if cfg.router_use == "scores" and not pin and not forced and slot not in ("private", "vision", "long", "reviewer"):',),
            ('    if cfg.router_use == "scores" and not pin and not forced and slot not in ("vision", "long", "reviewer"):',), 0,
            ('        scored, scored_why = from_scores(cfg, task.kind, board, trusted, rng)',)),
    Planted("reviewer-vendor", "inverted test", "When the author is known, put reviewers from another vendor first.",
            "src/crossvet/routing.py", 188,
            ('    models = cfg.slot_models(slot)', '    if slot == "reviewer" and author:'),
            ('        other = [m for m in models if providers.split(m)[0] != providers.split(author)[0]]',),
            ('        other = [m for m in models if providers.split(m)[0] == providers.split(author)[0]]',), 0,
            ('        models = other + [m for m in models if m not in other]',)),
    Planted("lock-fetch", "race", "Hold the lock for less time in LockedDB.execute; the server's threads share it.",
            "src/crossvet/store.py", 61,
            ('    def execute(self, sql: str, params: Any = ()) -> Result:', '        """Run one statement and read all of its rows."""'),
            ('        with self.lock:', '            cursor = self.connection.execute(sql, params)',
             '            return Result(cursor.fetchall(), cursor.rowcount, cursor.lastrowid)'),
            ('        with self.lock:', '            cursor = self.connection.execute(sql, params)',
             '        return Result(cursor.fetchall(), cursor.rowcount, cursor.lastrowid)'), 2),
    Planted("judge-bool", "type check", "Simplify the check on the judge's score; keep refusing anything but a whole number from 1 to 5.",
            "src/crossvet/score.py", 77,
            ('    data = read_json(reply.text) or {}', '    score = data.get("score")'),
            ('    if not isinstance(score, int) or isinstance(score, bool) or not 1 <= score <= 5:',),
            ('    if not isinstance(score, int) or not 1 <= score <= 5:',), 0,
            ('        return None, reply.cost or 0.0',)),
    Planted("sample-salt", "ignored argument", "Simplify the sampling hash; a turn must be sampled the same way on every run.",
            "src/crossvet/score.py", 55,
            ('def sampled(turn_id: int, rate: float, salt: str = "judge") -> bool:',
             '    """Decide in code, and the same way every time, whether a turn is in the sample."""',
             '    if rate <= 0:', '        return False'),
            ('    digest = hashlib.sha256(f"{salt}:{turn_id}".encode()).digest()',),
            ('    digest = hashlib.sha256(str(turn_id).encode()).digest()',), 0,
            ('    return int.from_bytes(digest[:4], "big") / 2**32 < rate',)),
    Planted("trust-flip", "inverted test", "Trust the judge until there are enough pairs to test it; after that, only if it agrees with your ratings often enough.",
            "src/crossvet/score.py", 208,
            ('    overall = stats(pairs)',),
            ('    trusted = overall["n"] < TRUST_MIN or overall["agreement"] >= TRUST_AGREE',),
            ('    trusted = overall["n"] >= TRUST_MIN or overall["agreement"] >= TRUST_AGREE',), 0,
            ('    return {"overall": overall, "kinds": {k: stats(v) for k, v in sorted(per_kind.items())}, "trusted": trusted}',)),
    Planted("standard-error", "wrong formula", "Report a cautious score: the mean minus one standard error.",
            "src/crossvet/score.py", 244,
            ('            mean = sum(scores) / len(scores)',
             '            spread = math.sqrt(sum((x - mean) ** 2 for x in scores) / (len(scores) - 1)) if len(scores) > 1 else 2.0'),
            ('            board[kind][model] = {"n": len(scores), "score": round(mean, 3), "low": round(mean - spread / math.sqrt(len(scores)), 3),',),
            ('            board[kind][model] = {"n": len(scores), "score": round(mean, 3), "low": round(mean - spread / len(scores), 3),',), 0,
            ('                                  "cost": round(sum(c for _, c in items) / len(items), 6)}',)),
    Planted("rollback-sign", "comparison", "Roll back a score route only when it scored worse than before by more than the margin.",
            "src/crossvet/tuning.py", 127,
            ('        if len(rows) >= enough:', '            after = sum(r["score"] for r in rows) / len(rows)'),
            ('            if after < before - cv.config.margin:',),
            ('            if after < before + cv.config.margin:',), 0,
            ('                cv.lab.set_route_status(route["id"], "rolled_back")',)),
    Planted("week-unit", "wrong unit", "Change at most one route per kind of task a week.", "src/crossvet/tuning.py", 133,
            (),
            ('    changed = {r["kind"] for r in cv.lab.routes() if r["decided"] and r["decided"] >= now - WEEK',),
            ('    changed = {r["kind"] for r in cv.lab.routes() if r["decided"] and r["decided"] >= now - 7',), 0,
            ('               and r["status"] in ("accepted", "rolled_back", "replaced")}',)),
    Planted("prune-running", "lost filter", "Prune finished handoffs older than `days`.", "src/crossvet/care.py", 211,
            ('    state = cv.store.db.execute("DELETE FROM relay_state WHERE ts < ?", (cutoff,)).rowcount', '    cv.store.db.commit()'),
            ('    handoffs = cv.lab.db.execute("DELETE FROM handoffs WHERE ts < ? AND status != \'running\'", (cutoff,)).rowcount',),
            ('    handoffs = cv.lab.db.execute("DELETE FROM handoffs WHERE ts < ?", (cutoff,)).rowcount',), 0,
            ('    cv.lab.db.commit()',)),
    # Clean changes: no bug. A blocker or major finding on one of these is a false alarm.
    Planted("clean-rename", "clean", "Rename the cursor variable in executemany.", "src/crossvet/store.py", 67,
            ('    def executemany(self, sql: str, params: Any) -> Result:', '        """Run one statement for each set of parameters."""'),
            ('        with self.lock:', '            cursor = self.connection.executemany(sql, params)',
             '            return Result([], cursor.rowcount, cursor.lastrowid)'),
            ('        with self.lock:', '            cur = self.connection.executemany(sql, params)',
             '            return Result([], cur.rowcount, cur.lastrowid)'), None),
    Planted("clean-names", "clean", "Use a clearer variable name in from_scores.", "src/crossvet/routing.py", 153,
            (),
            ('    best = max(c["low"] for c in cells.values())', '    close = [m for m, c in cells.items() if c["low"] >= best - cfg.margin]'),
            ('    best = max(cell["low"] for cell in cells.values())',
             '    close = [m for m, cell in cells.items() if cell["low"] >= best - cfg.margin]'), None,
            ('    ranked = order(cfg, close, "cheapest") + sorted((m for m in cells if m not in close), key=lambda m: -cells[m]["low"])',)),
    Planted("clean-day", "clean", "Name the seconds-per-day constant in prune.", "src/crossvet/care.py", 208,
            ('def prune(cv: Crossvet, days: float = 30) -> str:',
             '    """Drop kept tool-call reasoning and finished handoffs older than ``days``; turns are never removed."""'),
            ('    cutoff = time.time() - days * 86400',),
            ('    day = 86400', '    cutoff = time.time() - days * day'), None,
            ('    state = cv.store.db.execute("DELETE FROM relay_state WHERE ts < ?", (cutoff,)).rowcount',)),
    Planted("clean-split", "clean", "Split the minimum-answers rule into two lines.", "src/crossvet/tuning.py", 126,
            (),
            ('        enough = max(5, cv.config.min_scores // 4)',),
            ('        minimum = cv.config.min_scores // 4', '        enough = max(5, minimum)'), None,
            ('        if len(rows) >= enough:',)),
    Planted("clean-rubric", "clean", "Pull the rubric lookup out of the judge's prompt line.", "src/crossvet/score.py", 74,
            ('    """Ask the judge; return its verdict (``None`` unless it is valid JSON with a score of 1 to 5) and the cost."""',),
            ('    prompt = f"<rubric>\\n{RUBRIC.get(kind, RUBRIC[\'general\'])}\\n</rubric>\\n\\n<request>\\n{question}\\n</request>\\n\\n<answer>\\n{answer}\\n</answer>"',),
            ('    rubric = RUBRIC.get(kind, RUBRIC["general"])',
             '    prompt = f"<rubric>\\n{rubric}\\n</rubric>\\n\\n<request>\\n{question}\\n</request>\\n\\n<answer>\\n{answer}\\n</answer>"'), None),
    Planted("clean-comment", "clean", "Comment the zero-rate guard in sampled.", "src/crossvet/score.py", 56,
            ('    """Decide in code, and the same way every time, whether a turn is in the sample."""',),
            ('    if rate <= 0:',),
            ('    if rate <= 0:  # a rate of 0 (or less) samples nothing',), None,
            ('        return False',)),
)

SETS: dict[str, tuple[Planted, ...]] = {"planted": CASES, "hard": HARD, "all": CASES + HARD}


def run(cv: Crossvet, reviewers: list[str], cases: tuple[Planted, ...] = CASES,
        on_result: Callable[[dict[str, Any]], None] | None = None) -> list[dict[str, Any]]:
    """Have each reviewer review each case; return one row per (reviewer, case)."""
    from crossvet.review import review_once

    rows = []
    for reviewer in [cv.config.resolve(r) for r in reviewers]:
        for case in cases:
            row: dict[str, Any] = {"reviewer": reviewer, "case": case.name, "kind": case.kind, "clean": case.clean,
                                   "caught": False, "false_alarm": False, "kept": 0, "dropped": 0, "other": 0, "cost": 0.0,
                                   "why_dropped": [], "error": ""}
            try:
                findings, cost = review_once(cv, case.diff(), case.task, reviewer)
                kept = [f for f in findings if not f.dropped]
                if case.clean:
                    row.update(false_alarm=any(f.severity in ALARM for f in kept), other=len(kept))
                else:
                    near = [f for f in kept if f.file == case.path and abs(f.line - case.line) <= NEAR]
                    row.update(caught=bool(near), other=len(kept) - len(near))
                row.update(kept=len(kept), dropped=len(findings) - len(kept), cost=cost,
                           why_dropped=[f.dropped[:160] for f in findings if f.dropped][:5])
            except (ProviderError, RuntimeError, ValueError) as exc:
                row["error"] = str(exc)[:200]
            rows.append(row)
            if on_result:
                on_result(row)
    return rows


def summary(rows: list[dict[str, Any]]) -> dict[str, dict[str, float]]:
    """Return per reviewer: caught, cases, rate, other, dropped, cost, cost_per_catch, clean, false_alarms."""
    out: dict[str, dict[str, float]] = {}
    for reviewer in dict.fromkeys(r["reviewer"] for r in rows):
        mine = [r for r in rows if r["reviewer"] == reviewer and not r["error"]]
        bugs = [r for r in mine if not r.get("clean")]
        clean = [r for r in mine if r.get("clean")]
        caught = sum(r["caught"] for r in bugs)
        cost = sum(r["cost"] for r in mine)
        out[reviewer] = {"caught": caught, "cases": len(bugs), "rate": caught / len(bugs) if bugs else 0.0,
                         "other": sum(r["other"] for r in bugs), "dropped": sum(r["dropped"] for r in mine), "cost": cost,
                         "cost_per_catch": cost / caught if caught else 0.0, "clean": len(clean),
                         "false_alarms": sum(r["false_alarm"] for r in clean), "clean_notes": sum(r["other"] for r in clean),
                         "errors": sum(1 for r in rows if r["reviewer"] == reviewer and r["error"])}
    return out


def results_page(rows: list[dict[str, Any]], command: str, set_name: str = "planted") -> str:
    """Return the results page in Markdown, every number computed from ``rows``."""
    stats = summary(rows)
    names = list(dict.fromkeys(r["case"] for r in rows))
    planted = [n for n in names if not next(r for r in rows if r["case"] == n).get("clean")]
    clean = [n for n in names if n not in planted]
    intro = f"{len(planted)} changes to Crossvet's own code, each with one planted bug"
    if clean:
        intro += f", and {len(clean)} clean changes with no bug"
    lines = [f"# Review benchmark ({set_name} set), {time.strftime('%Y-%m-%d')}", "", f"Command: `{command}`", "",
             intro + ". A bug counts as caught when a finding that passed the checks in `review.check` points at its line "
             "(one line either side)." + (" On a clean change, a kept finding marked blocker or major is a false alarm." if clean else ""),
             "", "| Reviewer | Caught | Other findings | Dropped by the checks | Cost | Cost per bug caught |"
             + (" False alarms |" if clean else ""), "|---|---:|---:|---:|---:|---:|" + ("---:|" if clean else "")]
    for m, s in stats.items():
        per_catch = f"${s['cost_per_catch']:.4f}" if s["caught"] else "-"
        alarms = f" {int(s['false_alarms'])} of {int(s['clean'])} |" if clean else ""
        lines.append(f"| `{m}` | {int(s['caught'])} of {int(s['cases'])} | {int(s['other'])} | {int(s['dropped'])} | "
                     f"${s['cost']:.4f} | {per_catch} |" + alarms)
    lines += ["", "## Per case", "", "| Case | Kind | " + " | ".join(f"`{m}`" for m in stats) + " |", "|---|---|" + "---|" * len(stats)]
    for case in names:
        cells = []
        for reviewer in stats:
            row = next(r for r in rows if r["case"] == case and r["reviewer"] == reviewer)
            if row["error"]:
                cells.append("error")
            elif row.get("clean"):
                cells.append("false alarm" if row["false_alarm"] else "quiet" if not row["other"] else f"{row['other']} note(s)")
            else:
                cells.append("caught" if row["caught"] else "missed")
        lines.append(f"| {case} | {next(r['kind'] for r in rows if r['case'] == case)} | " + " | ".join(cells) + " |")
    lines += ["", "## Limits", "", f"- {len(names)} small changes; one run per reviewer and case.",
              "- A reviewer that names the right problem on a different line counts as a miss; one that flags the line for another reason counts as a catch.",
              "- `results.jsonl` next to this page has every row.", ""]
    return "\n".join(lines)
