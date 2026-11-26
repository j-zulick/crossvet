"""The review benchmark: does a reviewer catch a bug planted in a real change?

Each case is a small change to Crossvet's own code (the functions are the real ones from this
repository) with one bug planted on a known line: an off-by-one, a wrong unit, SQL built from text,
a key written to a log, an inverted check, a missing ``await``, a cap that never stops, a mutable
default, a swallowed error, the wrong price, a comparison that leaks timing, a cap counted the
wrong way round. Scoring is code: a reviewer catches the bug when one of its findings that passed
``review.check`` points at the planted line (one line either side counts). Findings elsewhere are
counted as "other findings"; they are not graded.

    crossvet bench --review -m sol -m opus           every case, each reviewer, a results page
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


@dataclass(frozen=True)
class Planted:
    """A change with one planted bug."""

    name: str
    kind: str
    task: str
    path: str
    start: int                 # new-side line number of the first context line
    before: tuple[str, ...]    # context lines before the change
    removed: tuple[str, ...]   # lines the change takes out
    added: tuple[str, ...]     # lines the change puts in; one holds the bug
    bug: int                   # index into ``added`` of the planted bug
    after: tuple[str, ...] = ()

    @property
    def line(self) -> int:
        """Return the planted bug's line number on the new side."""
        return self.start + len(self.before) + self.bug

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


def run(cv: Crossvet, reviewers: list[str], cases: tuple[Planted, ...] = CASES,
        on_result: Callable[[dict[str, Any]], None] | None = None) -> list[dict[str, Any]]:
    """Have each reviewer review each case; return one row per (reviewer, case)."""
    from crossvet.review import review_once

    rows = []
    for reviewer in [cv.config.resolve(r) for r in reviewers]:
        for case in cases:
            row: dict[str, Any] = {"reviewer": reviewer, "case": case.name, "kind": case.kind, "caught": False, "kept": 0,
                                   "dropped": 0, "other": 0, "cost": 0.0, "error": ""}
            try:
                findings, cost = review_once(cv, case.diff(), case.task, reviewer)
                kept = [f for f in findings if not f.dropped]
                near = [f for f in kept if f.file == case.path and abs(f.line - case.line) <= NEAR]
                row.update(caught=bool(near), kept=len(kept), dropped=len(findings) - len(kept), other=len(kept) - len(near), cost=cost)
            except (ProviderError, RuntimeError, ValueError) as exc:
                row["error"] = str(exc)[:200]
            rows.append(row)
            if on_result:
                on_result(row)
    return rows


def summary(rows: list[dict[str, Any]]) -> dict[str, dict[str, float]]:
    """Return ``{reviewer: {"caught", "cases", "rate", "other", "dropped", "cost", "cost_per_catch"}}``."""
    out: dict[str, dict[str, float]] = {}
    for reviewer in dict.fromkeys(r["reviewer"] for r in rows):
        mine = [r for r in rows if r["reviewer"] == reviewer and not r["error"]]
        caught = sum(r["caught"] for r in mine)
        cost = sum(r["cost"] for r in mine)
        out[reviewer] = {"caught": caught, "cases": len(mine), "rate": caught / len(mine) if mine else 0.0,
                         "other": sum(r["other"] for r in mine), "dropped": sum(r["dropped"] for r in mine), "cost": cost,
                         "cost_per_catch": cost / caught if caught else 0.0}
    return out


def results_page(rows: list[dict[str, Any]], command: str) -> str:
    """Return the results page in Markdown, every number computed from ``rows``."""
    stats = summary(rows)
    lines = [f"# Review benchmark, {time.strftime('%Y-%m-%d')}", "", f"Command: `{command}`", "",
             f"{len(CASES)} changes to Crossvet's own code, each with one planted bug. A bug counts as caught when a finding that "
             "passed the checks in `review.check` points at its line (one line either side).", "",
             "| Reviewer | Caught | Other findings | Dropped by the checks | Cost | Cost per bug caught |", "|---|---:|---:|---:|---:|---:|"]
    for m, s in stats.items():
        per_catch = f"${s['cost_per_catch']:.4f}" if s["caught"] else "-"
        lines.append(f"| `{m}` | {int(s['caught'])} of {int(s['cases'])} | {int(s['other'])} | {int(s['dropped'])} | "
                     f"${s['cost']:.4f} | {per_catch} |")
    lines += ["", "## Per case", "", "| Case | Kind | " + " | ".join(f"`{m}`" for m in stats) + " |", "|---|---|" + "---|" * len(stats)]
    for case in dict.fromkeys(r["case"] for r in rows):
        cells = []
        for reviewer in stats:
            row = next(r for r in rows if r["case"] == case and r["reviewer"] == reviewer)
            cells.append("error" if row["error"] else "caught" if row["caught"] else "missed")
        lines.append(f"| {case} | {next(r['kind'] for r in rows if r['case'] == case)} | " + " | ".join(cells) + " |")
    lines += ["", "## Limits", "", "- Twelve small, synthetic changes; one run per reviewer and case.",
              "- A reviewer that names the right problem on a different line counts as a miss; one that flags the line for another reason counts as a catch.",
              "- `results.jsonl` next to this page has every row.", ""]
    return "\n".join(lines)
