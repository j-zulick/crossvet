"""Measure which model to use for which kind of task, and write the answer into the config.

Each case has an answer key that code checks: no model grades another model. ``run`` asks every
model every case, ``leaderboard`` scores them per kind of task, and ``best_value`` picks, for
each slot, the cheapest model within 10% of the best score. The cases are small and synthetic:
they separate models that cannot do a job from models that can, not good from great.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from dataclasses import dataclass

from open_deep_research.chat.hub import Hub, strip_fences
from open_deep_research.chat.providers import ProviderError

VALUE_MARGIN = 0.10
SLOT_KINDS = {"quick": ("quick", "summarize", "extract"), "balanced": ("writing",), "strong": ("code", "reasoning")}


@dataclass(frozen=True)
class Case:
    """One task with a scorer that returns 0.0 to 1.0 from the answer text."""

    name: str
    kind: str
    prompt: str
    score: Callable[[str], float]


def _has_all(*needles: str) -> Callable[[str], float]:
    return lambda text: sum(n.lower() in text.lower() for n in needles) / len(needles)


def _number(expected: str) -> Callable[[str], float]:
    def score(text: str) -> float:
        numbers = re.findall(r"-?\d[\d,]*\.?\d*", text.replace("$", ""))
        try:
            return 1.0 if numbers and abs(float(numbers[-1].replace(",", "").rstrip(".")) - float(expected)) < 1e-9 else 0.0
        except ValueError:
            return 0.0
    return score


def _json_fields(expected: dict[str, object]) -> Callable[[str], float]:
    def score(text: str) -> float:
        try:
            data = json.loads(strip_fences(text))
        except ValueError:
            return 0.0
        if not isinstance(data, dict):
            return 0.0
        return sum(str(data.get(k, "")).strip().lower() == str(v).lower() for k, v in expected.items()) / len(expected)
    return score


def _summary(must: tuple[str, ...], max_words: int) -> Callable[[str], float]:
    def score(text: str) -> float:
        kept = sum(m.lower() in text.lower() for m in must) / len(must)
        return kept if len(text.split()) <= max_words else kept * 0.5
    return score


def _python_function(name: str, checks: list[tuple[tuple, object]]) -> Callable[[str], float]:
    """Score code by reading it, not running it: it must parse and define the function.

    Running model-written code on the user's machine is not something a benchmark should do by
    default, so behaviour is checked only with ``crossvet chat bench --run-code`` (see ``run_code_score``).
    """
    def score(text: str) -> float:
        import ast

        code = _code_block(text)
        try:
            tree = ast.parse(code)
        except SyntaxError:
            return 0.0
        return 1.0 if any(isinstance(n, ast.FunctionDef) and n.name == name for n in ast.walk(tree)) else 0.3
    score.function_name = name  # type: ignore[attr-defined]
    score.checks = checks  # type: ignore[attr-defined]
    return score


def _code_block(text: str) -> str:
    match = re.search(r"```(?:python|py)?\s*\n(.*?)```", text, re.S)
    return match.group(1) if match else text


def run_code_score(text: str, name: str, checks: list[tuple[tuple, object]], timeout: float = 5.0) -> float:
    """Run the function in a separate Python process with a time limit; share of checks passed."""
    import subprocess  # noqa: S404
    import sys
    import tempfile

    harness = _code_block(text) + "\nimport json,sys\nchecks=json.loads(sys.argv[1])\nok=0\n" \
        f"for args,want in checks:\n    try:\n        ok+=({name}(*args)==want)\n    except Exception:\n        pass\nprint(ok)\n"
    with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False) as handle:
        handle.write(harness)
    try:
        out = subprocess.run([sys.executable, "-I", handle.name, json.dumps([[list(a), w] for a, w in checks])],  # noqa: S603
                             capture_output=True, text=True, timeout=timeout)
        return int(out.stdout.strip() or 0) / len(checks)
    except (subprocess.TimeoutExpired, ValueError):
        return 0.0


_ARTICLE = ("Northwind Hardware said on Tuesday it will close 14 of its 212 stores by March, cutting about 380 jobs. "
            "Chief executive Dana Whitlock blamed a 9% fall in same-store sales and higher freight costs. The company "
            "will keep its online business, which grew 21% last year, and will open two distribution centres in Ohio.")
CASES: tuple[Case, ...] = (
    Case("capital", "quick", "What is the capital of Australia? Answer with the city name only.", _has_all("Canberra")),
    Case("boiling", "quick", "At sea level, at what temperature in degrees Celsius does water boil? Number only.", _number("100")),
    Case("store-closures", "summarize", f"Summarize in at most 40 words:\n\n{_ARTICLE}",
         _summary(("14", "380", "online"), 40)),
    Case("two-sentences", "summarize", f"Give the two most important facts in two sentences:\n\n{_ARTICLE}",
         _summary(("14", "Northwind"), 60)),
    Case("invoice", "extract", 'Extract as JSON with keys "invoice", "total" and "due" (YYYY-MM-DD): '
         "Invoice INV-2291 for $1,480.50 is due on 14 March 2026.",
         _json_fields({"invoice": "INV-2291", "total": "1480.50", "due": "2026-03-14"})),
    Case("contact", "extract", 'Return JSON with keys "name" and "email": "Reach Priya Raman at priya.raman@example.org before Friday."',
         _json_fields({"name": "Priya Raman", "email": "priya.raman@example.org"})),
    Case("subject-line", "writing", "Write an email subject line of at most 8 words announcing that the office is closed on "
         "Monday 3 March for maintenance. Include the word 'closed' and the date.", _summary(("closed", "3 March"), 8)),
    Case("polite-decline", "writing", "Write a two-sentence reply declining a meeting on Thursday and proposing Friday at 10am.",
         _summary(("Thursday", "Friday", "10"), 60)),
    Case("trains", "reasoning", "A train leaves at 09:10 and arrives at 13:55 after stopping for 25 minutes on the way. "
         "How many minutes was it moving? Give the number last.", _number("260")),
    Case("discount", "reasoning", "A $240 coat is discounted 15%, then a further 10% off the reduced price. "
         "What is the final price in dollars? Give the number last.", _number("183.60")),
    Case("slugify", "code", "Write a Python function slugify(text) that lowercases text, replaces each run of characters that "
         "are not letters or digits with one hyphen, and strips leading and trailing hyphens. Return only the code.",
         _python_function("slugify", [(("Hello, World!",), "hello-world"), (("  A--B  ",), "a-b"), (("x",), "x")])),
    Case("chunks", "code", "Write a Python function chunks(items, n) that returns a list of lists of at most n items, in order. "
         "Return only the code.", _python_function("chunks", [(([1, 2, 3, 4, 5], 2), [[1, 2], [3, 4], [5]]), (([], 3), [])])),
)


def run(hub: Hub, models: list[str], cases: tuple[Case, ...] = CASES, run_code: bool = False,
        on_result: Callable[[dict], None] | None = None) -> list[dict]:
    """Ask every model every case; return one row per (model, case)."""
    rows: list[dict] = []
    for model in models:
        for case in cases:
            row = {"model": model, "case": case.name, "kind": case.kind, "score": 0.0, "cost": None, "error": ""}
            try:
                answer = hub.ask(case.prompt, model=model, use_memory=False, save=False, author="bench", want_json=False)
                row["score"] = case.score(answer.text)
                if run_code and hasattr(case.score, "checks") and row["score"] == 1.0:
                    row["score"] = run_code_score(answer.text, case.score.function_name, case.score.checks)  # type: ignore[attr-defined]
                row["cost"] = answer.cost
            except (ProviderError, RuntimeError) as exc:
                row["error"] = str(exc)[:200]
            rows.append(row)
            if on_result:
                on_result(row)
    return rows


def leaderboard(rows: list[dict]) -> dict[str, dict[str, dict[str, float | None]]]:
    """``{kind: {model: {"score": mean, "cost": total or None}}}``."""
    board: dict[str, dict[str, dict[str, float | None]]] = {}
    for kind in sorted({r["kind"] for r in rows}):
        board[kind] = {}
        for model in dict.fromkeys(r["model"] for r in rows):
            mine = [r for r in rows if r["kind"] == kind and r["model"] == model]
            costs = [r["cost"] for r in mine if r["cost"] is not None]
            board[kind][model] = {"score": sum(r["score"] for r in mine) / len(mine),
                                  "cost": sum(costs) if len(costs) == len(mine) else None}
    return board


def best_value(rows: list[dict]) -> dict[str, list[str]]:
    """For each slot, models within 10% of the best score on that slot's kinds, cheapest first."""
    board = leaderboard(rows)
    slots: dict[str, list[str]] = {}
    for slot, kinds in SLOT_KINDS.items():
        totals: dict[str, tuple[float, float | None]] = {}
        for model in dict.fromkeys(r["model"] for r in rows):
            cells = [board[k][model] for k in kinds if k in board and model in board[k]]
            if not cells:
                continue
            costs = [c["cost"] for c in cells]
            totals[model] = (sum(c["score"] for c in cells) / len(cells), None if None in costs else sum(costs))  # type: ignore[arg-type]
        if not totals:
            continue
        top = max(score for score, _ in totals.values())
        good = [(cost if cost is not None else float("inf"), -score, model) for model, (score, cost) in totals.items()
                if score >= top - VALUE_MARGIN and score > 0]
        slots[slot] = [model for _, _, model in sorted(good)]
    return slots


def table(rows: list[dict]) -> str:
    """Return the leaderboard as text."""
    board = leaderboard(rows)
    models = list(dict.fromkeys(r["model"] for r in rows))
    width = max(len(m) for m in models) + 2
    lines = ["kind".ljust(11) + "".join(m.ljust(width) for m in models)]
    for kind, cells in board.items():
        lines.append(kind.ljust(11) + "".join(
            (f"{cells[m]['score']:.2f}" + ("" if cells[m]["cost"] is None else f" ${cells[m]['cost']:.4f}")).ljust(width) for m in models))
    return "\n".join(lines)
