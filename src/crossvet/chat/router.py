"""Which router picks the model, and Jev as a classifier and an answer check.

Routers (``[router] use`` in the settings, ``CROSSVET_CHAT_ROUTER`` to override, ``--router``):

    rules                 the text rules in classify.py (free, the default)
    jev                   Jev names the kind of task and the difficulty; the slots and routes still pick the model.
                          When Jev is unsure or fails, the rules decide.
    openrouter-auto       OpenRouter's Auto Router picks the model (openrouter/auto)
    openrouter-auto-code  OpenRouter's router for coding work (openrouter/auto-code)
    jev-router            TypeSafe's Jev Router on OpenRouter picks the model and reasoning effort (typesafe/jev-router)

With a hosted router, the slot the rules pick is still kept as the fallback when the hosted
router's call fails a check, and the model it chose is recorded as ``served_by``.

Jev is TypeSafe's decision model: it answers typed questions (a choice, a yes/no probability)
about text instead of writing text. It is reached through OpenRouter's Decisions API with the
same ``OPENROUTER_API_KEY``. Input is billed; output is free.

The answer check (``[router] check = "jev"``) asks Jev whether an answer addresses the request.
Code decides with a threshold: below it, the guard moves to the next model, as it does for an
empty answer. Any Jev error lets the answer through.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

import httpx

from crossvet.chat.classify import KINDS, Task

ROUTERS = ("rules", "jev", "learned", "openrouter-auto", "openrouter-auto-code", "jev-router")
HOSTED = {
    "openrouter-auto": "openrouter:openrouter/auto",
    "openrouter-auto-code": "openrouter:openrouter/auto-code",
    "jev-router": "openrouter:typesafe/jev-router",
}
DECISIONS_URL = "https://openrouter.ai/api/alpha/decisions"
DEFAULT_JEV_MODEL = "~typesafe/jev-latest"
KIND_CRITERIA = {
    "code": "Writing, fixing, explaining or reviewing program code, scripts, queries or configuration.",
    "review": "Critiquing or finding flaws in a plan, text or answer the user supplies.",
    "writing": "Drafting or rewriting prose: emails, posts, letters, descriptions.",
    "summarize": "Shortening or summarizing text the user supplies.",
    "extract": "Pulling items out of text, or converting it to a structure such as JSON or a table.",
    "translate": "Translating between languages.",
    "reasoning": "Analysis, planning, comparison, math or step-by-step reasoning.",
    "fresh": "Needs current information: news, prices, recent events, anything that changes over time.",
    "quick": "One short factual question with a short answer.",
    "general": "Anything else.",
}
DIFFICULTY_CRITERIA = {
    "1": "Easy: a small, well-defined task a small model handles.",
    "2": "Normal: everyday work that needs a capable model.",
    "3": "Hard: long, ambiguous, high-stakes or expert work that needs the strongest model.",
}
ANSWER_CRITERIA = {
    "true": "The answer responds to what was asked, even if it is brief or declines with a reason.",
    "false": "The answer is off-topic, answers a different question, or is cut off before saying anything useful.",
}


class JevError(RuntimeError):
    """A Jev call failed."""


@dataclass
class JevResult:
    """Jev's answers and what they cost."""

    answers: dict[str, Any]
    cost: float | None
    model: str = ""


class Jev:
    """Calls Jev through OpenRouter's Decisions API."""

    def __init__(self, model: str = "", transport: httpx.BaseTransport | None = None, timeout: float = 15.0) -> None:
        """Use ``model`` (default ``~typesafe/jev-latest``); ``transport`` is for tests."""
        self.model = model or DEFAULT_JEV_MODEL
        self.transport = transport
        self.timeout = timeout

    def decide(self, state: dict[str, str], questions: dict[str, Any]) -> JevResult:
        """Ask Jev ``questions`` about ``state``; raise ``JevError`` on any failure."""
        key = os.environ.get("OPENROUTER_API_KEY", "")
        if not key:
            raise JevError("OPENROUTER_API_KEY is not set")
        body = {"model": self.model, "state": state, "questions": questions}
        try:
            with httpx.Client(timeout=self.timeout, transport=self.transport) as client:
                response = client.post(DECISIONS_URL, headers={"Authorization": f"Bearer {key}", "X-Title": "Crossvet chat"}, json=body)
        except httpx.HTTPError as exc:
            raise JevError(f"{type(exc).__name__} calling OpenRouter") from exc
        if response.status_code >= 400:
            raise JevError(f"HTTP {response.status_code} from the Decisions API: {response.text[:200]}")
        try:
            data = response.json()
            answers = dict(data["answers"])
        except (ValueError, KeyError, TypeError) as exc:
            raise JevError("unexpected reply shape from the Decisions API") from exc
        cost = (data.get("usage") or {}).get("cost")
        return JevResult(answers, float(cost) if isinstance(cost, (int, float)) else None, str(data.get("model") or ""))

    def classify(self, prompt: str, fallback: Task, min_confidence: float = 0.5) -> tuple[Task, float | None, str]:
        """Return Jev's kind and difficulty for ``prompt``, the cost, and a note; ``fallback`` where Jev is unsure."""
        result = self.decide({"request": prompt[:30_000]}, {
            "kind": {"type": "choice", "instructions": "What kind of task is this request?", "criteria": KIND_CRITERIA},
            "difficulty": {"type": "choice", "instructions": "How hard is this request to do well?", "criteria": DIFFICULTY_CRITERIA},
        })
        kind_answer, diff_answer = result.answers.get("kind") or {}, result.answers.get("difficulty") or {}
        kind, kind_conf = str(kind_answer.get("choice", "")), float(kind_answer.get("confidence") or 0)
        diff, diff_conf = str(diff_answer.get("choice", "")), float(diff_answer.get("confidence") or 0)
        notes = []
        if kind in KINDS and kind_conf >= min_confidence:
            notes.append(f"Jev says {kind} (confidence {kind_conf:.2f})")
        else:
            notes.append(f"Jev was unsure of the kind ({kind or 'no answer'}, {kind_conf:.2f}), so the rules' {fallback.kind} stands")
            kind = fallback.kind
        if diff in DIFFICULTY_CRITERIA and diff_conf >= min_confidence:
            difficulty = int(diff)
            notes.append(f"difficulty {difficulty} ({diff_conf:.2f})")
        else:
            difficulty = fallback.difficulty
            notes.append(f"the rules' difficulty {difficulty} stands")
        note = "; ".join(notes)
        return Task(kind, difficulty, note, fallback.wants_json), result.cost, note

    def addresses(self, request: str, answer: str) -> tuple[float, float | None]:
        """Return Jev's probability that ``answer`` addresses ``request``, and the cost."""
        result = self.decide({"request": request[:12_000], "answer": answer[:16_000]}, {
            "addresses": {"type": "noul", "instructions": "Does the answer address the request?", "criteria": ANSWER_CRITERIA}})
        value = (result.answers.get("addresses") or {}).get("noul")
        if not isinstance(value, (int, float)):
            raise JevError("Jev gave no probability")
        return float(value), result.cost


def chosen(config_router: str, override: str | None = None) -> str:
    """Return the router in force: ``override``, else ``CROSSVET_CHAT_ROUTER``, else the settings."""
    name = (override or os.environ.get("CROSSVET_CHAT_ROUTER", "") or config_router or "rules").strip()
    if name not in ROUTERS:
        raise ValueError(f"router must be one of {', '.join(ROUTERS)}; got {name!r}")
    return name
