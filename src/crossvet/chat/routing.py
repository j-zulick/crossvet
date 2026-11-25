"""Turn a classified task into an ordered list of models to try, with the reason in words.

All of it is code, in this order:

1. The task's kind picks a slot from the config's routes; pasted code makes a quick or general
   request a code task.
2. Difficulty and the ``effort`` override move it up or down the quick → balanced → strong ladder.
3. Images, audio and PDFs move it to the slot for that input (``[inputs]``: vision, audio, long),
   and models that say they don't take the input are skipped.
4. ``[kinds]`` puts the models named for that kind of task first.
5. The goal reorders: ``best`` goes to the strongest slot, ``cheapest`` starts from the cheapest
   models and climbs, ``fastest`` is ordered by measured speed in the hub. ``[router] cascade``
   starts from the quick slot and climbs one slot at a time when an answer fails a check.
6. An input too long for the slot's models moves it to the ``long`` slot.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from crossvet.chat.classify import Task, classify
from crossvet.chat.config import GOALS, LADDER, SLOTS, Config
from crossvet.chat.inputs import Inputs

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
    goal: str = "auto"         # best | cheapest | fastest | auto
    private: str = ""          # why the request stays on your machine ("" = it may leave)
    inputs: list[str] = field(default_factory=list)  # input types besides text (image, audio, pdf)
    ordered: bool = False      # the goal or cascade set the order; the tuned table does not reorder it

    def explain(self) -> str:
        """One readable sentence per step of the decision."""
        first = self.candidates[0] if self.candidates else "(no model configured)"
        return f"{self.task.kind} task, difficulty {self.task.difficulty} → slot '{self.slot}' → {first}. " + " ".join(
            r.rstrip(".") + "." for r in self.reasons)


def _fits(model: str, config: Config, input_tokens: int) -> bool:
    context = config.info(model).context
    return not context or input_tokens + config.max_output_tokens <= context


def _unique(models: list[str]) -> list[str]:
    return list(dict.fromkeys(models))


def _price(config: Config, model: str) -> float | None:
    info = config.info(model)
    return None if info.input is None or info.output is None else info.input + info.output


def by_price(config: Config, models: list[str]) -> list[str]:
    """Order ``models`` cheapest first (input plus output price per million tokens); unpriced models keep their order, last."""
    priced = sorted((m for m in models if _price(config, m) is not None), key=lambda m: _price(config, m))  # type: ignore[arg-type,return-value]
    return priced + [m for m in models if _price(config, m) is None]


def takes(config: Config, model: str, needed: list[str]) -> bool | None:
    """Whether ``model`` takes every input in ``needed``: True, False, or None when its settings don't say."""
    stated = config.info(model).takes
    if not needed:
        return True
    if not stated:
        return None
    return all(t in stated for t in needed)


def route(prompt: str, config: Config, *, slot: str | None = None, effort: str = "auto",
          context_text: str = "", task: Task | None = None, inputs: Inputs | None = None, goal: str = "auto") -> Decision:
    """Choose the slot and the ordered candidates for ``prompt``."""
    task = task or classify(prompt)
    inputs = inputs or Inputs()
    goal = goal if goal in GOALS else "auto"
    if goal == "auto":
        goal = config.goal
    reasons = [f"Classified as {task.kind} because {task.reason}"]
    if inputs.code and task.kind in ("quick", "general") and not slot:
        task = Task("code", max(task.difficulty, 2), "the request contains code", task.wants_json)
        reasons = [f"Classified as code because {task.reason}"]
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
    if goal == "best" and not slot and chosen in LADDER and chosen != LADDER[-1]:
        chosen = LADDER[-1]
        reasons.append("The goal is the best answer, so it goes to the strongest slot")
    needed = inputs.types()
    by_input = next((config.input_slots[t] for t in needed if config.slots.get(config.input_slots[t])), None) if not slot else None
    if by_input and by_input != chosen:
        chosen = by_input
        reasons.append(f"It includes {inputs.describe()}, so it goes to the '{chosen}' slot")
    candidates = config.slot(chosen)
    if not config.slots.get(chosen) and candidates:
        reasons.append(f"The '{chosen}' slot is empty, so the nearest configured slot is used")
    if not slot and config.kinds.get(task.kind) and not by_input:
        candidates = _unique(config.kinds[task.kind] + candidates)
        reasons.append(f"[kinds] names the models to try first for {task.kind}")
    climb = (goal == "cheapest" or config.cascade) and not slot and chosen in LADDER and not by_input
    if climb:
        ladder = _unique([m for name in LADDER for m in (by_price(config, config.slots.get(name, [])) if goal == "cheapest"
                                                        else config.slots.get(name, []))])
        if ladder:
            candidates = ladder
            why = "the goal is the cheapest answer that passes" if goal == "cheapest" else "[router] cascade is on"
            reasons.append(f"Because {why}, it starts with the quick models and moves up a slot only when an answer fails a check")
    elif goal == "cheapest" and not slot:
        candidates = by_price(config, candidates)
        reasons.append("The goal is the cheapest answer, so the cheapest models go first")
    if needed:
        able = [m for m in candidates if takes(config, m, needed)]
        unknown = [m for m in candidates if takes(config, m, needed) is None]
        refused = [m for m in candidates if takes(config, m, needed) is False]
        if refused and (able or unknown):
            candidates = able + unknown
            reasons.append(f"Skipped {', '.join(refused)}: the settings say they don't take {' or '.join(needed)}")
        elif able and unknown:
            candidates = able + unknown
            reasons.append(f"Models the settings say take {' and '.join(needed)} go first")
        elif refused and not (able or unknown):
            reasons.append(f"No model in the slot says it takes {' or '.join(needed)}; trying them anyway")
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
    return Decision(task, chosen, fitting, reasons, goal=goal, inputs=needed, ordered=climb or (goal == "cheapest" and not slot))
