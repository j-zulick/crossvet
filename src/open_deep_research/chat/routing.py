"""Turn a classified task into an ordered list of models to try, with the reason in words.

All of it is code: the task's kind picks a slot from the config's routes, difficulty and the
``effort`` override move it up or down the quick → balanced → strong ladder, and an input too
long for the slot's models moves it to the ``long`` slot.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from open_deep_research.chat.classify import Task, classify
from open_deep_research.chat.config import LADDER, SLOTS, Config

EFFORTS = ("low", "auto", "high")
CHARS_PER_TOKEN = 4  # rough, and on the safe side for English


def estimate_tokens(text: str) -> int:
    """Rough token count for ``text``."""
    return len(text) // CHARS_PER_TOKEN + 1


@dataclass
class Decision:
    """Which models to try for a request, and why."""

    task: Task
    slot: str
    candidates: list[str]
    reasons: list[str] = field(default_factory=list)
    router: str = "rules"      # what chose: rules, jev, a hosted router (router.py), or "manual" for a named slot or model
    overhead_cost: float | None = None   # what deciding cost (a Jev call), on top of the answer
    explored: bool = False     # the second choice was put first on purpose ([tuning] explore)

    def explain(self) -> str:
        """One readable sentence per step of the decision."""
        first = self.candidates[0] if self.candidates else "(no model configured)"
        return f"{self.task.kind} task, difficulty {self.task.difficulty} → slot '{self.slot}' → {first}. " + " ".join(
            r.rstrip(".") + "." for r in self.reasons)


def _fits(model: str, config: Config, input_tokens: int) -> bool:
    context = config.info(model).context
    return not context or input_tokens + config.max_output_tokens <= context


def route(prompt: str, config: Config, *, slot: str | None = None, effort: str = "auto",
          context_text: str = "", task: Task | None = None) -> Decision:
    """Choose the slot and the ordered candidates for ``prompt``."""
    task = task or classify(prompt)
    reasons = [f"Classified as {task.kind} because {task.reason}"]
    if slot:
        if slot not in SLOTS:
            raise ValueError(f"slot must be one of {', '.join(SLOTS)}")
        chosen = slot
        reasons.append(f"You asked for the '{slot}' slot")
    else:
        chosen = config.routes.get(task.kind, "balanced")
        if chosen in LADDER:
            index = LADDER.index(chosen)
            if task.difficulty >= 3 and index < len(LADDER) - 1:
                index = len(LADDER) - 1
                reasons.append("It looks hard, so it goes to the strongest slot")
            if effort == "high" and index < len(LADDER) - 1:
                index += 1
                reasons.append("Effort is high, so it moves up one slot")
            elif effort == "low" and index > 0:
                index -= 1
                reasons.append("Effort is low, so it moves down one slot")
            chosen = LADDER[index]
    candidates = config.slot(chosen)
    if not config.slots.get(chosen) and candidates:
        reasons.append(f"The '{chosen}' slot is empty, so the nearest configured slot is used")
    input_tokens = estimate_tokens(prompt + context_text)
    fitting = [m for m in candidates if _fits(m, config, input_tokens)]
    if candidates and not fitting:
        long_models = [m for m in config.slot("long") if _fits(m, config, input_tokens)] if config.slots.get("long") else []
        if long_models:
            chosen, fitting = "long", long_models
            reasons.append(f"The input is about {input_tokens:,} tokens, too long for that slot, so it goes to 'long'")
        else:
            fitting = candidates
            reasons.append(f"The input is about {input_tokens:,} tokens and may not fit; no longer-context model is configured")
    elif len(fitting) < len(candidates):
        reasons.append("Models whose context window is too small for this input were skipped")
    return Decision(task, chosen, fitting, reasons)
