"""A weekly report of the chat: cost per model, ratings per kind of task, routing, and proposed table changes.

Every number is counted in code from the local store (answers, their costs, ratings and the
signals recorded on them). Proposals come from ``tuning.proposals``, the same rule
``crossvet chat tune`` uses. ``send_to_langfuse`` posts the finished report as one trace.
"""

from __future__ import annotations

import time
from collections import defaultdict
from typing import TYPE_CHECKING, Any

from crossvet.chat.tuning import proposals, stats

if TYPE_CHECKING:
    from crossvet.chat.hub import Hub


def _money(value: float | None) -> str:
    return "-" if value is None else f"${value:.4f}"


def _share(part: int, whole: int) -> str:
    return "-" if not whole else f"{part / whole:.0%}"


def weekly(hub: Hub, days: float = 7, now: float | None = None) -> str:
    """Return the report for the last ``days`` as markdown."""
    now = now or time.time()
    since = now - days * 86400
    answers = hub.memory.answers(since=since)
    table = stats(hub, since)
    start, end = time.strftime("%b %d, %Y", time.localtime(since)), time.strftime("%b %d, %Y", time.localtime(now))
    lines = [f"# Crossvet chat: {start} to {end}", ""]
    priced = [a.cost for a in answers if a.cost is not None]
    lines.append(f"- **Answers:** {len(answers)}; cost known for {len(priced)}: {_money(sum(priced) if priced else None)} in all.")
    rated = sum(s.rated for s in table.values())
    good = sum(s.good for s in table.values())
    lines.append(f"- **Rated:** {rated}, of which {good} good ({_share(good, rated)}).")
    lines.append("")

    per_model: dict[str, list[Any]] = defaultdict(list)
    for answer in answers:
        if answer.model:
            per_model[answer.model].append(answer)
    lines += ["## Cost per model", "", "| Model | Answers | Cost | Per answer |", "|---|---:|---:|---:|"]
    for model, rows in sorted(per_model.items(), key=lambda item: -sum(a.cost or 0 for a in item[1])):
        costs = [a.cost for a in rows if a.cost is not None]
        total = sum(costs) if costs else None
        lines.append(f"| {model} | {len(rows)} | {_money(total)} | {_money(total / len(costs) if costs else None)} |")
    if not per_model:
        lines.append("| (no answers) | 0 | - | - |")
    lines.append("")

    per_kind: dict[str, list[Any]] = defaultdict(list)
    for (kind, _model), stat in table.items():
        per_kind[kind].append(stat)
    lines += ["## Ratings per kind of task", "",
              "| Kind | Answers | Rated | Good | Retried, switched or rated bad |", "|---|---:|---:|---:|---:|"]
    for kind, rows in sorted(per_kind.items()):
        n = sum(s.answers for s in rows)
        r = sum(s.rated for s in rows)
        g = sum(s.good for s in rows)
        trouble = sum(s.retried + s.switched + (s.rated - s.good) for s in rows)
        lines.append(f"| {kind} | {n} | {r} | {_share(g, r)} | {_share(trouble, n)} |")
    if not per_kind:
        lines.append("| (no answers) | 0 | 0 | - | - |")
    lines.append("")

    lines += routing(hub, answers, since)

    found = proposals(hub, table, hub.config.min_ratings)
    lines += ["## Proposed changes to the routing table", ""]
    if not found:
        lines.append("None: no model beats the current first choice on your ratings. Rate answers with /good and /bad.")
    for p in found:
        lines.append(f"- **{p.kind}:** put {p.model} first{' (weak: few ratings)' if p.weak else ''}. {p.evidence}. "
                     f"Apply with `crossvet chat tune --apply {p.kind}`.")
    lines.append("")
    return "\n".join(lines)


def routing(hub: Hub, answers: list[Any], since: float) -> list[str]:
    """Return the routing section of the report.

    It counts answers, ratings and escalations per slot, private and input-routed answers, and what
    the same answers would have cost from the first strong-slot model (from its configured prices).
    """
    ratings: dict[int, list[tuple[str, float]]] = {}
    for rating in hub.memory.ratings(since=since):
        ratings.setdefault(rating.turn_id, []).append((rating.name, rating.value))
    lines = ["## Routing", "", "| Slot | Answers | Good when rated | Escalated | Cost |", "|---|---:|---:|---:|---:|"]
    per_slot: dict[str, list[Any]] = defaultdict(list)
    for answer in answers:
        per_slot[str(answer.meta.get("slot") or "-")].append(answer)
    for slot, rows in sorted(per_slot.items(), key=lambda item: -len(item[1])):
        rated = [r for r in rows if any(n == "user-feedback" for n, _ in ratings.get(r.id, []))]
        good = sum([v for n, v in ratings[r.id] if n == "user-feedback"][-1] >= 0.5 for r in rated)
        escalated = sum(len(r.meta.get("attempts") or []) > 1 for r in rows)
        costs = [r.cost for r in rows if r.cost is not None]
        lines.append(f"| {slot} | {len(rows)} | {_share(good, len(rated))} | {_share(escalated, len(rows))} | "
                     f"{_money(sum(costs) if costs else None)} |")
    if not per_slot:
        lines.append("| (no answers) | 0 | - | - | - |")
    inputs_in = sum(int((a.meta.get("usage") or {}).get("input", 0) or 0) for a in answers)
    cached_in = sum(int((a.meta.get("usage") or {}).get("cached", 0) or 0) for a in answers)
    private = sum(bool(a.meta.get("private")) for a in answers)
    by_input = sum(bool(a.meta.get("inputs")) for a in answers)
    lines += ["", f"- **Kept on your machine:** {private}. **Routed by images, audio or PDFs:** {by_input}."]
    if inputs_in:
        lines.append(f"- **Prompt cache:** {cached_in:,} of {inputs_in:,} input tokens ({_share(cached_in, inputs_in)}) "
                     "were read from a vendor's cache.")
    strong = (hub.config.slot("strong") or [""])[0]
    info = hub.config.info(strong) if strong else None
    if info and info.input is not None and info.output is not None:
        actual, baseline, counted = 0.0, 0.0, 0
        for answer in answers:
            usage = (answer.meta.get("usage") or {})
            if answer.cost is None or not usage:
                continue
            counted += 1
            actual += answer.cost
            baseline += (usage.get("input", 0) * info.input + usage.get("output", 0) * info.output) / 1_000_000
        if counted:
            lines.append(f"- **Against always using {strong}:** {_money(actual)} spent on {counted} priced answers, "
                         f"{_money(baseline)} at {strong}'s prices for the same tokens: "
                         f"{_share(round(100 * max(baseline - actual, 0)), round(100 * baseline)) if baseline else '-'} saved.")
        else:
            lines.append(f"- **Against always using {strong}:** no answer has both a cost and token counts yet.")
    else:
        lines.append("- **Against always using the strong slot:** set input and output prices for its first model to compare.")
    from crossvet.chat.learned import load

    model = load(hub.memory)
    if model and model.accuracy is not None:
        lines.append(f"- **Learned router:** trained on {model.examples} rated answers; on the newest {model.held_out} it picked the "
                     f"slot you rated well {model.accuracy:.0%} of the time, the rules {model.rules_accuracy:.0%}.")
    lines.append("")
    return lines


def send_to_langfuse(report: str, days: float, client: Any | None = None) -> str:
    """Post the report as one Langfuse trace named ``crossvet-weekly-report``; return its trace id."""
    if client is None:
        from crossvet.chat.langfuse_sync import default_client

        client = default_client()
    span = client.start_observation(name="crossvet-weekly-report", as_type="span", input={"days": days}, output=report,
                                    metadata={"kind": "report"})
    trace_id = str(getattr(span, "trace_id", "") or "")
    span.end()
    client.flush()
    return trace_id
