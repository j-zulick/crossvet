"""Tune the routes ``auto`` uses from your own ratings. Only you accept a change, and any change can be rolled back.

``stats`` counts, per kind of task and model, how many of the answers Crossvet chose that you rated
were good. ``propose`` suggests putting another model first for a kind when, on at least
``MIN_RATINGS`` ratings each, it was rated good clearly more often than the model in use. A proposal
changes nothing until ``crossvet tune accept ID``; ``crossvet tune rollback ID`` undoes it.
"""

from __future__ import annotations

from collections import defaultdict
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from crossvet.core import Crossvet

MIN_RATINGS = 5
MARGIN = 0.15  # the other model's good-rate must beat the current one by this much


def stats(cv: Crossvet, since: float = 0.0) -> dict[str, dict[str, dict[str, float]]]:
    """Return ``{kind: {model: {"good", "bad", "rate"}}}`` from rated answers that Crossvet chose."""
    table: dict[str, dict[str, dict[str, float]]] = defaultdict(lambda: defaultdict(lambda: {"good": 0, "bad": 0, "rate": 0.0}))
    for rating in cv.lab.ratings(since):
        decision = cv.lab.decision(turn_id=rating["turn_id"])
        if decision is None:
            continue
        cell = table[decision["kind"]][decision["model"]]
        cell["good" if rating["rating"] > 0 else "bad"] += 1
    for models in table.values():
        for cell in models.values():
            total = cell["good"] + cell["bad"]
            cell["rate"] = cell["good"] / total if total else 0.0
    return {k: dict(v) for k, v in table.items()}


def current_first(cv: Crossvet, kind: str) -> str:
    """Return the model ``auto`` puts first for a kind today."""
    pinned = cv.lab.pinned().get(kind)
    if pinned:
        return pinned
    from crossvet.config import callable_now

    slot = cv.config.routes.get(kind, "balanced")
    return next((m for m in cv.config.slot_models(slot) if callable_now(m)), "")


def propose(cv: Crossvet, since: float = 0.0) -> list[dict[str, Any]]:
    """Record a proposal for each kind where another model was rated clearly better; return the open proposals."""
    for kind, models in stats(cv, since).items():
        now = current_first(cv, kind)
        mine = models.get(now)
        for model, cell in sorted(models.items(), key=lambda mc: -mc[1]["rate"]):
            if model == now or cell["good"] + cell["bad"] < MIN_RATINGS:
                continue
            if mine and mine["good"] + mine["bad"] >= MIN_RATINGS and cell["rate"] >= mine["rate"] + MARGIN:
                evidence = (f"{model}: {int(cell['good'])} of {int(cell['good'] + cell['bad'])} rated good "
                            f"({cell['rate']:.0%}); {now}: {int(mine['good'])} of {int(mine['good'] + mine['bad'])} "
                            f"({mine['rate']:.0%})")
                cv.lab.propose_route(kind, model, now, evidence)
                break
    return cv.lab.routes("proposed")


def text(cv: Crossvet) -> str:
    """Return the ratings table, open proposals and accepted routes as plain text."""
    lines = ["Ratings of answers Crossvet chose (good / rated):"]
    table = stats(cv)
    if not table:
        lines.append("  none yet: rate answers with /good or /bad (or `crossvet rate`)")
    for kind, models in sorted(table.items()):
        cells = ", ".join(f"{m} {int(c['good'])}/{int(c['good'] + c['bad'])}" for m, c in models.items())
        lines.append(f"  {kind:<10} {cells}")
    open_ = propose(cv)
    lines.append("\nProposals (`crossvet tune accept ID` or `crossvet tune reject ID`):")
    lines += [f"  #{r['id']} {r['kind']}: put {r['model']} first instead of {r['previous'] or 'the slot order'}. "
              f"{r['evidence']}" for r in open_] or ["  none"]
    accepted = cv.lab.routes("accepted")
    lines.append("\nAccepted routes (`crossvet tune rollback ID` undoes one):")
    lines += [f"  #{r['id']} {r['kind']} -> {r['model']}" for r in accepted] or ["  none"]
    return "\n".join(lines)
