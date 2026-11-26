"""Tune the routes ``auto`` uses from your ratings and from judged scores. Any change can be rolled back.

``stats`` counts, per kind of task and model, how many of the answers Crossvet chose that you rated
were good. ``propose`` suggests putting another model first for a kind when, on at least
``MIN_RATINGS`` ratings each, it was rated good clearly more often than the model in use.
``propose_from_scores`` suggests the best-value model from the judged leaderboard (score.py).
A proposal changes nothing until ``crossvet tune accept ID``; ``crossvet tune rollback ID`` undoes it.

``auto`` (``crossvet tune auto``, for a weekly schedule) is off unless ``[router] auto_tune = true``.
It first rolls back any score route whose model now scores clearly worse than the model it replaced,
then accepts at most one score proposal per kind of task, and never for a kind changed in the last
seven days. Every change is logged with its evidence.
"""

from __future__ import annotations

from collections import defaultdict
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from crossvet.core import Crossvet

MIN_RATINGS = 5
WEEK = 7 * 86400
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


class _NoExplore:
    def random(self) -> float:
        return 1.0


def propose_from_scores(cv: Crossvet) -> list[dict[str, Any]]:
    """Record a proposal for each kind where the judged leaderboard's best value is not the model used now."""
    from crossvet import routing, score

    board, trusted = score.leaderboard(cv, 30), score.calibration(cv)["trusted"]
    for kind in board:
        ranked, why = routing.from_scores(cv.config, kind, board, trusted, _NoExplore())  # type: ignore[arg-type]
        now = current_first(cv, kind)
        if ranked and ranked[0] != now:
            route = cv.lab.propose_route(kind, ranked[0], now, why, origin="scores")
            before = (board[kind].get(now) or {}).get("score")
            if before is not None and not cv.lab.get(f"route_before:{route}"):
                cv.lab.put(f"route_before:{route}", str(before))
    return [r for r in cv.lab.routes("proposed") if r["origin"] == "scores"]


def auto(cv: Crossvet, now: float | None = None) -> str:
    """Roll back score routes that did worse, then accept at most one score proposal per kind a week."""
    if not cv.config.auto_tune:
        return "Automatic route changes are off ([router] auto_tune = false): `crossvet tune` lists proposals for you to accept."
    import time as clock

    now = now or clock.time()
    lines = []
    for route in cv.lab.routes("accepted"):
        if route["origin"] != "scores" or not cv.lab.get(f"route_before:{route['id']}"):
            continue
        before = float(cv.lab.get(f"route_before:{route['id']}"))
        rows = cv.lab.db.execute("SELECT score FROM scores WHERE model = ? AND kind = ? AND ts >= ? AND score IS NOT NULL",
                                 (route["model"], route["kind"], route["decided"] or 0)).fetchall()
        enough = max(5, cv.config.min_scores // 4)
        if len(rows) >= enough:
            after = sum(r["score"] for r in rows) / len(rows)
            if after < before - cv.config.margin:
                cv.lab.set_route_status(route["id"], "rolled_back")
                lines.append(f"rolled back #{route['id']} ({route['kind']} -> {route['model']}): it scored {after:.2f} on "
                             f"{len(rows)} answers since, against {before:.2f} for {route['previous'] or 'the model before'}")
    changed = {r["kind"] for r in cv.lab.routes() if r["decided"] and r["decided"] >= now - WEEK
               and r["status"] in ("accepted", "rolled_back", "replaced")}
    for proposal in propose_from_scores(cv):
        if proposal["kind"] in changed:
            continue
        cv.lab.set_route_status(proposal["id"], "accepted")
        changed.add(proposal["kind"])
        lines.append(f"accepted #{proposal['id']} ({proposal['kind']} -> {proposal['model']}): {proposal['evidence']}")
    return "\n".join(lines) or "No change: no score route did worse, and no kind has a better-value model by its scores."
