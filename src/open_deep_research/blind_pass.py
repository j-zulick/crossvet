"""Blind first pass: reviewers outline the answer before they see the draft.

A draft anchors whoever reads it: reviewers tend to check what it says and miss what it
leaves out. With ``REVIEW_BLIND_PASS_ENABLED``, every reviewer first lists the most
important points a correct answer must make, each with the passage from the research
notes that supports it, **without seeing the draft**. Then, in code:

1. a point counts only when its passage appears verbatim in the notes (``quote_in_notes``);
2. a grounded point is *covered* when most of its passage's distinctive words, and any
   number in it, appear in the draft;
3. grounded points the draft does not cover become **omissions**: they are added to that
   reviewer's critique as missing perspectives, so they reach the vote and the reviser.

Each reviewer also sees its own outline when it critiques the draft, so it does not drop
its points just because the draft never made them. The outline call is short
(``REVIEW_BLIND_MAX_POINTS`` points, ``REVIEW_BLIND_MAX_TOKENS`` output tokens).
"""

from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

from pydantic import BaseModel, Field

from open_deep_research.cross_vendor_review import Critique, quote_in_notes

COVERAGE_THRESHOLD = 0.5
_STOP = set(
    "the and for with that this from have has had was were are been being which their there they them than then into onto over "
    "under about after before also more most less such only other some what when where while will would could should may might "
    "into each both these those over very just like among between within without upon your yours ours his her its our not".split()
)
_WORD = re.compile(r"[a-z][a-z'-]{3,}")
_NUM = re.compile(r"\d[\d,.]*")


class BlindPoint(BaseModel):
    """One point a correct answer must make."""

    point: str = Field(description="The point, in one sentence.")
    evidence_quote: str = Field(description="An EXACT quote from the research notes that supports the point.")


class BlindOutline(BaseModel):
    """A reviewer's outline of the answer, written before seeing the draft."""

    points: list[BlindPoint] = Field(default_factory=list)


BLIND_PROMPT = """Before you see anyone's report, outline the answer to this research question from the research notes alone.

Research question / brief:
{brief}

Research notes:
{notes}

List the {max_points} most important points a correct, complete answer must make, most important first. For each point give one sentence and an EXACT quote from the notes that supports it. Use only what the notes say; do not invent quotes."""

OUTLINE_REMINDER = """

Before seeing the draft, you outlined these points from the notes. Check whether the draft makes them; do not drop a point just because the draft never mentions it:
{points}"""


def _tokens(text: str) -> tuple[set[str], set[str]]:
    low = (text or "").lower()
    words = {w.strip("'-") for w in _WORD.findall(low)} - _STOP
    nums = {n.rstrip(".,").replace(",", "") for n in _NUM.findall(low)}
    return words, {n for n in nums if n}


def covered(point: BlindPoint, report: str, threshold: float = COVERAGE_THRESHOLD) -> bool:
    """Return True when the draft carries the point: its numbers, and most of its passage's distinctive words."""
    q_words, q_nums = _tokens(point.evidence_quote + " " + point.point)
    r_words, r_nums = _tokens(report)
    if q_nums and not (q_nums & r_nums):
        return False
    if not q_words:
        return bool(q_nums)
    return len(q_words & r_words) / len(q_words) >= threshold


@dataclass
class BlindResult:
    """What the blind pass found, per reviewer and overall."""

    outlines: dict[str, list[BlindPoint]] = field(default_factory=dict)
    failed: list[str] = field(default_factory=list)
    omissions: list[dict[str, str]] = field(default_factory=list)
    ungrounded: int = 0
    covered: int = 0

    def summary(self) -> dict[str, Any]:
        """Compact form for the review state and export."""
        return {
            "reviewers": len(self.outlines),
            "failed": self.failed,
            "points": sum(len(p) for p in self.outlines.values()),
            "covered": self.covered,
            "omitted": len(self.omissions),
            "ungrounded": self.ungrounded,
            "omissions": self.omissions,
        }


def assess(outlines: dict[str, list[BlindPoint]], notes: str, report: str) -> BlindResult:
    """Ground each point in the notes, check the draft covers it, and collect omissions (deduplicated)."""
    result = BlindResult(outlines=outlines)
    seen: set[str] = set()
    for model, points in outlines.items():
        for p in points:
            if not quote_in_notes(p.evidence_quote, notes):
                result.ungrounded += 1
                continue
            if covered(p, report):
                result.covered += 1
                continue
            key = re.sub(r"\s+", " ", p.evidence_quote.lower()).strip()
            if key in seen:
                continue
            seen.add(key)
            result.omissions.append({"reviewer": model, "point": p.point.strip(), "evidence": p.evidence_quote.strip()})
    return result


def add_omissions(critiques: dict[str, Critique], result: BlindResult) -> dict[str, Critique]:
    """Append each reviewer's omissions to its critique's missing perspectives."""
    out = dict(critiques)
    for model, crit in critiques.items():
        extra = [f'Omitted from the draft (outlined before reading it): {o["point"]} Notes: "{o["evidence"]}"'
                 for o in result.omissions if o["reviewer"] == model]
        if extra:
            out[model] = crit.model_copy(update={"missing_perspectives": list(crit.missing_perspectives) + extra})
    return out


def reminder(points: list[BlindPoint]) -> str:
    """Text appended to a reviewer's critique prompt: its own blind outline."""
    if not points:
        return ""
    return OUTLINE_REMINDER.format(points="\n".join(f"- {p.point}" for p in points))


Ask = Callable[[str], Awaitable[Any]]
"""ask(model) -> BlindOutline; raises on failure."""


async def outline_all(models: list[str], ask: Ask, max_points: int) -> tuple[dict[str, list[BlindPoint]], list[str]]:
    """Ask every reviewer for its blind outline in parallel; failures are listed, not fatal."""
    async def one(m: str) -> tuple[str, list[BlindPoint] | None]:
        try:
            got = await ask(m)
        except Exception:
            return m, None
        if not isinstance(got, BlindOutline):
            return m, None
        return m, got.points[:max_points]

    pairs = await asyncio.gather(*(one(m) for m in models))
    return {m: p for m, p in pairs if p is not None}, [m for m, p in pairs if p is None]


def notes_line(result: BlindResult) -> str:
    """One line for the report's Review notes."""
    s = result.summary()
    line = (f"Blind pass: {s['reviewers']} reviewer(s) outlined the answer before reading the draft; "
            f"{s['points']} point(s), {s['covered']} covered by the draft, {s['omitted']} grounded omission(s) added to the feedback")
    if s["ungrounded"]:
        line += f", {s['ungrounded']} dropped because their passage is not in the notes"
    if s["failed"]:
        line += f"; outline failed for {', '.join(s['failed'])}"
    return line + "."
