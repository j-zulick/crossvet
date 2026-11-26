"""The chat benchmark: measure which model to use for which kind of task.

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
from typing import TYPE_CHECKING

from crossvet.providers import ProviderError

if TYPE_CHECKING:
    from crossvet.core import Crossvet

VALUE_MARGIN = 0.10
ANSWER_KEEP = 600  # characters of each answer kept in the rows, so a low score can be checked against what the model said
SLOT_KINDS = {"quick": ("quick", "summarize", "extract"), "balanced": ("writing",), "strong": ("code", "reasoning"),
              "long": ("long",)}


@dataclass(frozen=True)
class Case:
    """One task with a scorer that returns 0.0 to 1.0 from the answer text."""

    name: str
    kind: str
    prompt: str
    score: Callable[[str], float]
    example: str = ""  # a reference answer that scores 1.0 (tests check it)


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


def strip_fences(text: str) -> str:
    """Remove a Markdown code fence around an answer."""
    match = re.match(r"^\s*```(?:json|python)?\s*(.*?)\s*```\s*$", text, re.S)
    return match.group(1) if match else text.strip()


_QUOTES = str.maketrans({"\u2018": "'", "\u2019": "'", "\u201c": '"', "\u201d": '"'})


def _text(value: object) -> str:
    """Lower case, trimmed, with typographic quotes made plain (Scotti\u2019s == Scotti's)."""
    return str(value).translate(_QUOTES).strip().lower()


def _same(got: object, want: object) -> bool:
    """Equal as text (case, spaces and quote style ignored), or as numbers when both read as numbers (1480.5 == "1480.50")."""
    a, b = _text(got), _text(want)
    if a == b:
        return True
    try:
        return abs(float(a.replace(",", "")) - float(b.replace(",", ""))) < 1e-9
    except ValueError:
        return False


def _json_object(text: str) -> dict | None:
    try:
        data = json.loads(strip_fences(text))
    except ValueError:
        return None
    return data if isinstance(data, dict) else None


def _json_fields(expected: dict[str, object]) -> Callable[[str], float]:
    def score(text: str) -> float:
        data = _json_object(text)
        if data is None:
            return 0.0
        return sum(_same(data.get(k, ""), v) for k, v in expected.items()) / len(expected)
    return score


def _json_list(key: str, expected: list[str]) -> Callable[[str], float]:
    """1.0 for the exact list in order; otherwise half the overlap (extra or missing names cost)."""
    def score(text: str) -> float:
        data = _json_object(text)
        got = data.get(key) if data else None
        if not isinstance(got, list):
            return 0.0
        got = [_text(g) for g in got]
        want = [_text(e) for e in expected]
        if got == want:
            return 1.0
        return 0.5 * len(set(got) & set(want)) / len(set(got) | set(want))
    return score


def _summary_without(must: tuple[str, ...], forbid: tuple[str, ...], max_words: int) -> Callable[[str], float]:
    """Like ``_summary``, and each forbidden string present (a superseded figure, say) halves the score."""
    keep = _summary(must, max_words)
    return lambda text: keep(text) * 0.5 ** sum(f.lower() in text.lower() for f in forbid)


def _clock(expected: str) -> Callable[[str], float]:
    """Score 1.0 when the last H:MM or HH:MM in the answer is ``expected`` (24-hour)."""
    def score(text: str) -> float:
        times = re.findall(r"\b(\d{1,2}):(\d{2})\b", text)
        return 1.0 if times and f"{int(times[-1][0]):02d}:{times[-1][1]}" == expected else 0.0
    return score


def _final_choice(options: tuple[str, ...], expected: str) -> Callable[[str], float]:
    """Of the names offered, the one mentioned last must be ``expected`` (so "not Ana but Ben" counts as Ben)."""
    def score(text: str) -> float:
        found = [(m.start(), o) for o in options for m in re.finditer(rf"\b{re.escape(o)}\b", text, re.I)]
        return 1.0 if found and max(found)[1] == expected else 0.0
    return score


def _bullets(count: int, max_words: int, must: tuple[str, ...], banned: str) -> Callable[[str], float]:
    """Share of four rules: exactly ``count`` "- " bullets, each within ``max_words``, every ``must`` present, no ``banned``."""
    def score(text: str) -> float:
        lines = [line.strip() for line in text.strip().splitlines() if line.strip()]
        bullets = [line[2:] for line in lines if line.startswith("- ")]
        rules = (len(bullets) == count and len(lines) == count,
                 bool(bullets) and all(len(b.split()) <= max_words for b in bullets),
                 all(m.lower() in text.lower() for m in must),
                 banned not in text)
        return sum(rules) / len(rules)
    return score


def _plain(max_words: int, banned: tuple[str, ...], must_any: tuple[str, ...]) -> Callable[[str], float]:
    """Share of three rules: within ``max_words``, none of ``banned`` (any form), at least one of ``must_any``."""
    def score(text: str) -> float:
        low = text.lower()
        rules = (len(text.split()) <= max_words, not any(b in low for b in banned), any(m in low for m in must_any))
        return sum(rules) / len(rules)
    return score


def _summary(must: tuple[str | tuple[str, ...], ...], max_words: int) -> Callable[[str], float]:
    """Share of ``must`` present (a tuple entry is met by any of its spellings, "6" or "six"), halved when over ``max_words``."""
    def present(item: str | tuple[str, ...], low: str) -> bool:
        return any(m.lower() in low for m in ((item,) if isinstance(item, str) else item))

    def score(text: str) -> float:
        low = _text(text)
        kept = sum(present(m, low) for m in must) / len(must)
        return kept if len(text.split()) <= max_words else kept * 0.5
    return score


def _python_function(name: str, checks: list[tuple[tuple, object]]) -> Callable[[str], float]:
    """Score code by reading it, not running it: it must parse and define the function.

    Running model-written code on the user's machine is not something a benchmark should do by
    default, so behaviour is checked only with ``crossvet bench --run-code`` (see ``run_code_score``).
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


# Every case below comes from used-car dealer work in Sarasota, Florida: facts from six web searches run on
# 2026-11-25 (marketplaces, dealer sites, listing snippets, CarEdge's doc fees), and our own notes on them.
_SEARCHES = ("On 2026-11-25 six web searches for used cars in Sarasota, Florida were run. Kelley Blue Book and iSeeCars "
             "appeared in five each. Sarasota Ford's own site and Edmunds appeared in four each; Sarasota Ford's was the "
             "only dealer site that ranked directly. TrueCar appeared in three; Cars.com, Carfax, Autotrader and CarGurus "
             "in two each. Other dealers appeared only through marketplace or directory pages.")
_CPO = ("Sarasota Ford's pages on Ford certified pre-owned vehicles say: a Blue certified vehicle passes a 139-point "
        "inspection; a Gold certified vehicle passes a 172-point inspection and must be under 6 years old with less than "
        "80,000 miles; certified vehicles include comprehensive limited warranty coverage of 12 months or 12,000 miles; "
        "and the program grants a 7-year or 100,000-mile powertrain limited warranty.")
CASES: tuple[Case, ...] = (
    Case("zip", "quick", "Sarasota Ford is at 707 S Washington Blvd., Sarasota, FL 34236. What is its ZIP code? Number only.",
         _number("34236")),
    Case("missing-search", "quick", f"{_SEARCHES}\n\nIn how many of the six searches did Sarasota Ford's own site not "
         "appear? Number only.", _number("2")),
    Case("search-summary", "summarize", f"Summarize in at most 40 words:\n\n{_SEARCHES}",
         _summary(("Kelley Blue Book", "Sarasota Ford"), 40)),
    Case("gold-certified", "summarize", f"In at most 30 words, say what a Gold certified vehicle must meet:\n\n{_CPO}",
         _summary(("172", ("6", "six"), "80,000"), 30)),
    Case("listing", "extract", 'Extract as JSON with keys "year", "make", "model", "trim", "miles" and "price" (numbers '
         'without commas or symbols): "Used 2019 Ford EcoSport Titanium for Sale · 115,176 Miles · $6,799"',
         _json_fields({"year": "2019", "make": "Ford", "model": "EcoSport", "trim": "Titanium", "miles": "115176",
                       "price": "6799"})),
    Case("dealer-address", "extract", 'Return JSON with keys "name", "street", "city" and "zip": '
         '"Gulf Coast Auto Brokers of Sarasota, 4343 Clark Rd, Sarasota, FL 34233"',
         _json_fields({"name": "Gulf Coast Auto Brokers of Sarasota", "street": "4343 Clark Rd", "city": "Sarasota",
                       "zip": "34233"})),
    Case("pickup-subject", "writing", "Write an email subject line of at most 8 words telling a customer their 2016 Nissan "
         "Rogue SV is ready for pickup. Include the words 'Rogue' and 'ready'.", _summary(("Rogue", "ready"), 8)),
    Case("test-drive-reply", "writing", "Write a two-sentence reply to a customer, declining a test drive on Thursday and "
         "offering Saturday at 10am instead.", _summary(("Thursday", "Saturday", "10"), 60)),
    Case("doc-fees", "reasoning", "CarEdge reports a $900 doc fee on used cars at Veterans Ford and $998 at Venice Honda; "
         "the Florida average is $973. How many dollars above the Florida average is Venice Honda's fee? Give the number "
         "last.", _number("25")),
    Case("out-the-door", "reasoning", "A used 2017 Ford Fusion Platinum is listed at $15,687. The dealer takes 5% off the "
         "list price, then adds a $900 doc fee. What is the total in dollars? Give the number last.", _number("15802.65")),
    Case("parse-miles", "code", 'Write a Python function parse_miles(text) that turns mileage text such as "115,176 Miles", '
         '"45,558 miles" or "71K mi" into an int number of miles (K means thousands). Return only the code.',
         _python_function("parse_miles", [(("115,176 Miles",), 115176), (("45,558 miles",), 45558), (("71K mi",), 71000)])),
    Case("parse-price", "code", 'Write a Python function parse_price(text) that turns prices such as "$6,799", "$11,994" '
         'or "15,687" into an int. Return only the code.',
         _python_function("parse_price", [(("$6,799",), 6799), (("$11,994",), 11994), (("15,687",), 15687)])),
)


# The sites each search returned on 2026-11-25, in the order they first appeared.
SEARCH_SITES = {
    "used car sales Sarasota Florida": ("Kelley Blue Book", "Carfax", "Cars.com", "Sarasota Ford", "TrueCar"),
    "used cars Sarasota FL": ("Kelley Blue Book", "Edmunds", "iSeeCars"),
    "used car dealers Sarasota FL": ("BBB", "CarEdge", "iSeeCars", "Kelley Blue Book", "DealerRater", "Autotrader",
                                     "Sarasota Ford", "Carfax"),
    "pre-owned cars for sale Sarasota": ("Edmunds", "iSeeCars", "TrueCar", "Kelley Blue Book", "CarGurus"),
    "certified pre-owned Sarasota dealership": ("Sarasota Ford", "iSeeCars", "Autotrader", "Edmunds"),
    "cheap used cars Sarasota buy here pay here": ("Kelley Blue Book", "CarGurus", "Cars.com", "Patch", "TrueCar",
                                                   "Sarasota Ford", "Edmunds", "iSeeCars"),
}


def _search_log() -> str:
    """Return a long checklist (about 9,000 words) of the Sarasota searches, with one answer and two traps in it."""
    queries = list(SEARCH_SITES)
    entries = []
    for i in range(1, 361):
        query = queries[i % len(queries)]
        sites = SEARCH_SITES[query]
        entries.append(f"Entry {i}. Checklist pass {1 + i // len(queries)} for the search '{query}': the sites recorded on "
                       f"2026-11-25, in order, were {', '.join(sites)}; {len(sites)} sites in all.")
    entries[36] = ("Entry 37. First tally of Sarasota Ford's own site across the six searches: 5. This tally is a draft and "
                   "will be rechecked.")
    entries[120] = "Entry 121. Tally of TrueCar across the six searches: 3."
    entries[240] = ("Entry 241. Recount of Sarasota Ford's own site across the six searches: 4. This replaces the draft "
                    "tally from entry 37.")
    return "\n".join(entries)


HARD_CASES: tuple[Case, ...] = (
    Case("count-letters", "quick", "How many times does the letter r appear in the words strawberry and raspberry combined? "
         "Number only.", _number("6"), "6"),
    Case("hours-to-seconds", "quick", "How many seconds are there in 3.5 hours? Number only.", _number("12600"), "12600"),
    Case("decimal-compare", "quick", "Which is larger, 9.11 or 9.9? Answer with that number only.", _number("9.9"), "9.9"),
    Case("corrected-figure", "summarize",
         "Summarize in at most 30 words, using only the corrected figures:\n\nOur first note said Sarasota Ford's own site "
         "appeared in five of the six searches for used cars in Sarasota, Florida. The recount found four, and it was still "
         "the only dealer site that ranked directly.",
         _summary_without(("four", "Sarasota Ford", "only"), ("five",), 30),
         "Sarasota Ford's own site appeared in four of six Sarasota used-car searches, the only dealer site that ranked directly."),
    Case("corrected-listing", "extract",
         'Return JSON with keys "year" (number), "make", "model", "trim", "price" (number) and "miles" (number) for the '
         'corrected listing: Our first note '
         "gave the used 2016 Nissan Rogue SV at Gettel Genesis of Sarasota as $11,949 with 45,585 miles. The TrueCar listing "
         "shows $11,994 and 45,558 miles; use the listing.",
         _json_fields({"year": "2016", "make": "Nissan", "model": "Rogue", "trim": "SV", "price": "11994", "miles": "45558"}),
         '{"year": 2016, "make": "Nissan", "model": "Rogue", "trim": "SV", "price": 11994, "miles": 45558}'),
    Case("directory-dealers", "extract",
         'Return a JSON object {"dealers": [...]} listing, in the order mentioned, the dealers that appeared only through '
         'marketplace or directory pages: "The results named Sarasota Ford, through its own site, and Gettel Hyundai of '
         "Sarasota, Scotti's Auto and Gulf Coast Auto Brokers of Sarasota, only through marketplace or directory pages. "
         'Sarasota Ford also appeared on Carfax."',
         _json_list("dealers", ["Gettel Hyundai of Sarasota", "Scotti's Auto", "Gulf Coast Auto Brokers of Sarasota"]),
         '{"dealers": ["Gettel Hyundai of Sarasota", "Scotti\'s Auto", "Gulf Coast Auto Brokers of Sarasota"]}'),
    Case("three-bullets", "writing",
         'Write exactly three bullet points, each a line starting with "- " and nothing else, announcing that the monthly plan '
         "goes from $12 to $15 on 1 May. At most 12 words per bullet. Mention both prices. No exclamation marks.",
         _bullets(3, 12, ("$12", "$15", "1 May"), "!"),
         "- The monthly plan changes price on 1 May.\n- It goes from $12 to $15 a month.\n- Your current features stay the same."),
    Case("plain-english", "writing",
         "Rewrite this for a customer in plain English, in at most 20 words, without the words utilize, leverage or synergy: "
         '"We will leverage our synergies to utilize existing infrastructure for faster delivery."',
         _plain(20, ("utiliz", "leverag", "synerg"), ("faster", "sooner", "quicker")),
         "We will use what we already have to get your order to you faster."),
    Case("time-zones", "reasoning",
         "A call starts at 16:30 in Pittsburgh on 15 January (UTC-5). What is the local time in Tokyo (UTC+9) when it starts? "
         "Give the time last, as HH:MM in 24-hour form.", _clock("06:30"), "Tokyo is 14 hours ahead, so it starts at 06:30"),
    Case("pumps", "reasoning",
         "Three pumps together fill a tank in 6 hours. Two of them, without the third, fill it in 10 hours. How many hours would "
         "the third pump alone take? Give the number last.", _number("15"), "1/6 - 1/10 = 1/15, so 15"),
    Case("price-back", "reasoning",
         "A price rises 20%, then the new price falls 20%. It is now $96. What was the original price in dollars? Give the number last.",
         _number("100"), "96 / (1.2 × 0.8) = 100"),
    Case("search-order", "reasoning",
         "In the Sarasota used-car searches, Cars.com appeared in fewer searches than TrueCar, Edmunds in more than TrueCar, "
         "and Kelley Blue Book in more than Edmunds. Which site appeared in the second fewest searches? Give the name last.",
         _final_choice(("Cars.com", "TrueCar", "Edmunds", "Kelley Blue Book"), "TrueCar"),
         "Fewest to most: Cars.com, TrueCar, Edmunds, Kelley Blue Book. Second fewest: TrueCar"),
    Case("merge-intervals", "code",
         "Write a Python function merge_intervals(intervals) that takes a list of [start, end] lists (in any order) and returns "
         "the merged intervals as a list of [start, end] lists sorted by start; intervals that touch, like [1, 4] and [4, 5], "
         "merge. Return only the code.",
         _python_function("merge_intervals", [(([[1, 3], [8, 10], [2, 6], [15, 18]],), [[1, 6], [8, 10], [15, 18]]),
                                              (([[1, 4], [4, 5]],), [[1, 5]]), (([],), [])]),
         "def merge_intervals(intervals):\n    out = []\n    for start, end in sorted(intervals):\n"
         "        if out and start <= out[-1][1]:\n            out[-1][1] = max(out[-1][1], end)\n"
         "        else:\n            out.append([start, end])\n    return out\n"),
    Case("parse-duration", "code",
         'Write a Python function parse_duration(text) that turns strings like "1h30m15s", "45s" or "2h" into a number of '
         'seconds (int). Units are h, m and s, each at most once, in that order. An empty string returns 0. Return only the code.',
         _python_function("parse_duration", [(("1h30m15s",), 5415), (("45s",), 45), (("2h",), 7200), (("",), 0)]),
         "import re\n\ndef parse_duration(text):\n    m = re.fullmatch(r'(?:(\\d+)h)?(?:(\\d+)m)?(?:(\\d+)s)?', text)\n"
         "    h, mi, s = (int(x or 0) for x in m.groups())\n    return h * 3600 + mi * 60 + s\n"),
    Case("roman", "code",
         "Write a Python function roman_to_int(text) that converts a Roman numeral (I, V, X, L, C, D, M; subtractive forms like "
         "IV and CM) to an int. Return only the code.",
         _python_function("roman_to_int", [(("MCMXCIV",), 1994), (("IV",), 4), (("LVIII",), 58)]),
         "def roman_to_int(text):\n    v = {'I': 1, 'V': 5, 'X': 10, 'L': 50, 'C': 100, 'D': 500, 'M': 1000}\n"
         "    total = 0\n    for a, b in zip(text, text[1:] + ' '):\n"
         "        total += -v[a] if b != ' ' and v[a] < v[b] else v[a]\n    return total\n"),
    Case("long-log", "long",
         "Below is our checklist of the Sarasota used-car searches. In how many of the six searches did Sarasota Ford's own "
         "site appear, after the recount? Give the number last.\n\n" + _search_log(), _number("4"),
         "The recount in entry 241 found 4, replacing the draft tally of 5 from entry 37: 4"),
)
SUITES: dict[str, tuple[Case, ...]] = {"standard": CASES, "hard": HARD_CASES, "all": CASES + HARD_CASES}


def run(cv: Crossvet, models: list[str], cases: tuple[Case, ...] = CASES, run_code: bool = False,
        on_result: Callable[[dict], None] | None = None) -> list[dict]:
    """Ask every model every case; return one row per (model, case)."""
    rows: list[dict] = []
    for model in models:
        for case in cases:
            row = {"model": model, "case": case.name, "kind": case.kind, "score": 0.0, "cost": None, "error": "", "answer": ""}
            try:
                answer = cv.ask(model, [{"role": "user", "content": case.prompt}], app="bench")
                row["answer"] = answer.text[:ANSWER_KEEP]
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
            if not mine:  # this model was not asked this kind of case (rows from separate runs)
                continue
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
            ("-" if m not in cells else f"{cells[m]['score']:.2f}" + ("" if cells[m]["cost"] is None else f" ${cells[m]['cost']:.4f}")).ljust(width)
        for m in models))
    return "\n".join(lines)


def best_per_kind(rows: list[dict]) -> dict[str, list[str]]:
    """For each kind of task the chat routes, models within 10% of the best score on it, cheapest first, then the rest."""
    from crossvet.classify import KINDS

    out: dict[str, list[str]] = {}
    for kind, cells in leaderboard(rows).items():
        ranked = sorted(((m, c) for m, c in cells.items() if (c["score"] or 0) > 0), key=lambda mc: -(mc[1]["score"] or 0))
        if kind not in KINDS or not ranked:
            continue
        top = ranked[0][1]["score"] or 0
        close = sorted((mc for mc in ranked if (mc[1]["score"] or 0) >= top * (1 - VALUE_MARGIN)),
                       key=lambda mc: (mc[1]["cost"] is None, mc[1]["cost"] or 0.0))
        out[kind] = [m for m, _ in close] + [m for m, _ in ranked if (m, _) not in close]
    return out


def results_page(rows: list[dict], *, date: str, suite: str, command: str, run_code: bool = False) -> str:
    """Return a results page in Markdown, every number computed from ``rows``.

    The page follows the shape of the published research-benchmark records: what ran, what it
    cost, the leaderboard, the best-value pick per slot, and the limits. Nothing is typed in by
    hand, so a page can only say what the run measured.
    """
    models = list(dict.fromkeys(r["model"] for r in rows))
    cases = list(dict.fromkeys(r["case"] for r in rows))
    failures = [r for r in rows if r.get("error")]
    per_kind = [len({r["case"] for r in rows if r["kind"] == k}) for k in dict.fromkeys(r["kind"] for r in rows)]
    spread = f"{min(per_kind)}" if min(per_kind) == max(per_kind) else f"{min(per_kind)} to {max(per_kind)}"
    costs = [r["cost"] for r in rows if r.get("cost") is not None]
    if not costs:
        cost = "not reported by the providers"
    else:
        cost = f"${sum(costs):.4f}" + ("" if len(costs) == len(rows) else f" for the {len(costs)} of {len(rows)} calls that reported one")
    lines = [
        f"# Chat benchmark, {date}",
        "",
        "| | |",
        "|---|---|",
        f"| Date | {date} |",
        f"| Models | {', '.join(f'`{m}`' for m in models)} |",
        f"| Suite | `{suite}`: {len(cases)} cases, {len(rows)} calls, {len(failures)} failed |",
        f"| Code answers | {'run in a separate process and checked' if run_code else 'read, not run (parse and define the function)'} |",
        f"| Cost | {cost} (as reported by each provider) |",
        f"| Command | `{command}` |",
        "",
        "## Score by kind of task",
        "",
        "Mean score from 0 to 1 per kind, scored in code against each case's answer key; cost is the total for that kind.",
        "",
        "```",
        table(rows),
        "```",
        "",
        "## Best value per slot",
        "",
        "The cheapest model within 10% of the best score on the slot's kinds of task.",
        "",
    ]
    for slot, ranked in best_value(rows).items():
        lines.append(f"- `{slot}`: {', '.join(f'`{m}`' for m in ranked) or '(none scored above 0)'}")
    if failures:
        lines += ["", "## Failed calls", ""] + [f"- `{r['model']}` on `{r['case']}`: {r['error']}" for r in failures]
    lines += [
        "",
        "## Limits",
        "",
        f"- Every case is synthetic and small; a kind's score rests on {spread} case(s).",
        "- One run per model and case: a single answer can move a kind's score by a lot.",
        "- Scores say which models fail a job, and on the hard suite which fall for its traps; they are not a general ranking.",
        "- `results.jsonl` next to this page has every row: model, case, kind, score, cost, any error and the start of the answer.",
        "",
    ]
    return "\n".join(lines)
