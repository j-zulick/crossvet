"""Choosing a model, only when you ask for it: name ``auto`` (or a slot or a goal) instead of a model.

    auto, crossvet/auto        Crossvet picks: the kind of task -> a slot -> the first callable model in it
    crossvet/<slot>            a slot you name: quick, balanced, strong, long, vision, reviewer, private
    crossvet/<goal>            best, cheapest or fastest across the slot for this kind of task

Every decision is made in code from the request alone (no model is asked) and is explained in
words: ``/why`` shows it, ``crossvet route TEXT`` shows it without calling anything. The rules:

1. A request that looks private (a key, a card or ID number, "confidential", ``[private]``) only goes
   to the ``private`` slot. With no private slot it is refused, never sent to a cloud model.
2. Images go to the ``vision`` slot; a request over ``[router] long_chars`` goes to ``long``.
3. Otherwise ``classify.py`` names the kind of task and its difficulty; ``[routes]`` maps the kind
   to a slot; a hard task (difficulty 3) moves quick and balanced up to strong.
4. A route you accepted with ``crossvet tune`` (tuning.py) puts its model first for that kind.
5. The goal orders the slot: ``auto`` keeps your order; ``cheapest`` and ``best`` sort by list price;
   ``fastest`` by the median time each model took in your own log.

The models after the first form the ladder that escalation climbs (core.py): after an error, an
empty answer or invalid JSON, the next model is tried. The ladder holds at most ``[router] max_steps``
models after the first (none with ``escalate = false``).
"""

from __future__ import annotations

import re
import statistics
from dataclasses import dataclass, field
from typing import Any

from crossvet import providers
from crossvet.classify import Task, classify
from crossvet.config import GOALS, SLOTS, Config, callable_now
from crossvet.providers import text_of

AUTO_NAMES = ("auto", "crossvet/auto")
LADDER = ("quick", "balanced", "strong")
_PRIVATE = re.compile(
    r"\[private\]|\bconfidential\b|\bdo not share\b|\bsk-[A-Za-z0-9_-]{16,}|\bAKIA[0-9A-Z]{16}\b|-----BEGIN [A-Z ]*PRIVATE KEY|"
    r"\b\d{3}-\d{2}-\d{4}\b|\b(?:\d[ -]?){15,16}\b",
    re.IGNORECASE)


class PrivateRequest(ValueError):
    """A request that looks private has nowhere private to go."""


@dataclass
class Decision:
    """Which model answers and why."""

    model: str
    slot: str
    goal: str
    kind: str
    difficulty: int
    reason: str
    ladder: list[str] = field(default_factory=list)  # the models to try, in order (model first)
    wants_json: bool = False

    def explain(self) -> str:
        """Return the decision in one paragraph."""
        rest = ", then ".join(self.ladder[1:]) if len(self.ladder) > 1 else "nothing (no other model in reach)"
        return (f"{self.model} answers. Kind of task: {self.kind} (difficulty {self.difficulty}): {self.reason}. "
                f"Slot: {self.slot}; goal: {self.goal}. If it fails, Crossvet tries {rest}.")

    def as_dict(self) -> dict[str, Any]:
        """Return the decision as plain data, as it is recorded."""
        return {"model": self.model, "slot": self.slot, "goal": self.goal, "kind": self.kind,
                "difficulty": self.difficulty, "reason": self.reason, "ladder": self.ladder}


def is_auto(name: str | None) -> bool:
    """Whether a model name asks Crossvet to choose."""
    low = (name or "").strip().lower()
    return low in AUTO_NAMES or (low.startswith("crossvet/") and low.split("/", 1)[1] in (*SLOTS, *GOALS))


def menu_names() -> list[str]:
    """Return the names that ask Crossvet to choose, for model menus."""
    return ["auto", *(f"crossvet/{s}" for s in SLOTS if s != "private"), *(f"crossvet/{g}" for g in GOALS if g != "auto")]


def has_image(messages: list[dict[str, Any]]) -> bool:
    """Whether the latest user message carries an image."""
    for message in reversed(messages):
        if message.get("role") == "user":
            content = message.get("content")
            return isinstance(content, list) and any(
                isinstance(p, dict) and p.get("type") in ("image_url", "image", "input_image") for p in content)
    return False


def looks_private(text: str) -> str:
    """Return what made ``text`` look private, or "" when nothing did."""
    match = _PRIVATE.search(text or "")
    if not match:
        return ""
    found = match.group(0)
    return found if found.lower() in ("[private]", "confidential", "do not share") else "something that looks like a key or ID number"


def _median_seconds(store: Any, model: str) -> float:
    if store is None:
        return float("inf")
    rows = store.db.execute("SELECT meta FROM turns WHERE role='assistant' AND model=? ORDER BY id DESC LIMIT 50",
                            (model,)).fetchall()
    import json

    seconds = [float(json.loads(r["meta"] or "{}").get("seconds") or 0) for r in rows]
    seconds = [s for s in seconds if s > 0]
    return statistics.median(seconds) if seconds else float("inf")


def order(cfg: Config, models: list[str], goal: str, store: Any = None) -> list[str]:
    """Order models for a goal; models without a price or a timing go last."""
    if goal in ("cheapest", "best"):
        def price(m: str) -> float:
            p = cfg.price(m)
            return float("inf") if p is None else p[0] + p[1]
        ranked = sorted(models, key=price)
        if goal == "best":
            priced = [m for m in ranked if cfg.price(m) is not None][::-1]
            return priced + [m for m in ranked if cfg.price(m) is None]
        return ranked
    if goal == "fastest":
        return sorted(models, key=lambda m: _median_seconds(store, m))
    return list(models)


def _callable(models: list[str]) -> list[str]:
    seen: list[str] = []
    for m in models:
        if m not in seen and callable_now(m):
            seen.append(m)
    return seen


def decide(cfg: Config, messages: list[dict[str, Any]], name: str = "auto", *, pinned: dict[str, str] | None = None,
           store: Any = None, author: str = "") -> Decision:
    """Choose the model for a request that named ``auto``, a slot or a goal."""
    low = (name or "auto").strip().lower()
    forced = low.split("/", 1)[1] if low.startswith("crossvet/") else ""
    goal = forced if forced in GOALS else cfg.goal
    text = next((text_of(m.get("content")) for m in reversed(messages) if m.get("role") == "user"), "")
    task: Task = classify(text)
    private = looks_private(text) if cfg.private_auto else ""
    if forced == "private" or private:
        slot, why = "private", (f"it looks private ({private})" if private else "you asked for the private slot")
    elif forced in SLOTS:
        slot, why = forced, f"you asked for the {forced} slot"
    elif has_image(messages):
        slot, why = "vision", "it carries an image"
    elif len(text) > cfg.long_chars:
        slot, why = "long", f"it is long ({len(text):,} characters)"
    else:
        slot = cfg.routes.get(task.kind, "balanced")
        why = task.reason
        if task.difficulty >= 3 and slot in ("quick", "balanced"):
            slot, why = "strong", why + "; hard tasks go to the strong slot"
    models = cfg.slot_models(slot)
    if slot == "reviewer" and author:
        other = [m for m in models if providers.split(m)[0] != providers.split(author)[0]]
        models = other + [m for m in models if m not in other]
    pin = (pinned or {}).get(task.kind) if slot not in ("private", "vision", "long") and not forced else None
    if pin:
        models = [pin, *[m for m in models if m != pin]]
        why += f"; your accepted route for {task.kind} puts {pin} first"
    ladder = _callable(order(cfg, models, goal, store) if not pin else [models[0], *order(cfg, models[1:], goal, store)])
    if slot == "private":
        if not ladder:
            raise PrivateRequest(f"this request {why[3:] if why.startswith('it ') else why}, and no private model is set, so "
                                 "it was not sent anywhere. Add [slots] private = [\"ollama:...\"] (a model on this "
                                 "computer), remove the private details, or name a model yourself.")
    else:
        if slot in LADDER:
            for higher in LADDER[LADDER.index(slot) + 1:]:
                ladder += [m for m in _callable(cfg.slot_models(higher)) if m not in ladder]
        if not ladder:
            raise ValueError("auto found no model it can call: add an API key (`crossvet doctor` shows which are set) "
                             "or fill [slots] in crossvet.toml")
    ladder = ladder[: 1 + (cfg.max_steps if cfg.escalate else 0)]  # only the models escalation would try
    return Decision(model=ladder[0], slot=slot, goal=goal, kind=task.kind, difficulty=task.difficulty, reason=why,
                    ladder=ladder, wants_json=task.wants_json)


def stronger(cfg: Config, last: dict[str, Any] | None) -> str:
    """Return the slot one step up from a recorded decision (``/retry stronger``)."""
    slot = (last or {}).get("slot", "balanced")
    if slot in LADDER and slot != "strong":
        return LADDER[LADDER.index(slot) + 1]
    return "strong"
