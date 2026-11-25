"""A weekly report of the chat: cost per model, ratings per kind of task, and proposed table changes.

Every number is counted in code from the local store (answers, their costs, ratings and the
signals recorded on them). Proposals come from ``tuning.proposals``, the same rule
``crossvet chat tune`` uses. ``send_to_langfuse`` posts the finished report as one trace.
"""

from __future__ import annotations

import time
from collections import defaultdict
from typing import TYPE_CHECKING, Any

from open_deep_research.chat.tuning import proposals, stats

if TYPE_CHECKING:
    from open_deep_research.chat.hub import Hub


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

    found = proposals(hub, table, hub.config.min_ratings)
    lines += ["## Proposed changes to the routing table", ""]
    if not found:
        lines.append("None: no model beats the current first choice on your ratings. Rate answers with /good and /bad.")
    for p in found:
        lines.append(f"- **{p.kind}:** put {p.model} first{' (weak: few ratings)' if p.weak else ''}. {p.evidence}. "
                     f"Apply with `crossvet chat tune --apply {p.kind}`.")
    lines.append("")
    return "\n".join(lines)


def send_to_langfuse(report: str, days: float, client: Any | None = None) -> str:
    """Post the report as one Langfuse trace named ``crossvet-weekly-report``; return its trace id."""
    if client is None:
        from open_deep_research.chat.langfuse_sync import default_client

        client = default_client()
    span = client.start_observation(name="crossvet-weekly-report", as_type="span", input={"days": days}, output=report,
                                    metadata={"kind": "report"})
    trace_id = str(getattr(span, "trace_id", "") or "")
    span.end()
    client.flush()
    return trace_id
