"""A rough cost estimate for one research run, before any model is called.

    crossvet research "QUESTION" --estimate [--effort quick|standard|deep]

The number of calls per stage comes from the settings in force (after ``--effort``); tokens per
call are fixed assumptions (``TOKENS``); prices come from OpenRouter's catalog that
``crossvet setup`` caches, or OpenRouter's price for the same model when it is called directly.
Two columns:

- **low:** one supervisor round, two researchers, three tool calls each, three pages read each;
- **high:** every limit reached (all rounds, all parallel researchers, every tool call).

Real runs usually land between them. The estimate is judgment applied to the settings, not a
measurement; the one measured reference is the Nov 17 pilot ($0.19 without review, $0.36 with a
two-vendor panel). ``MAX_RUN_USD`` / ``--max-usd`` is the hard stop.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

# (input tokens, output tokens) per call, by stage. Assumptions, not measurements.
TOKENS = {
    "clarify and brief": (3_000, 600),
    "supervisor": (6_000, 1_000),
    "researchers": (8_000, 800),
    "page summaries": (9_000, 900),
    "compression": (20_000, 3_000),
    "report": (30_000, 6_000),
    "review: critiques and vote": (34_000, 1_800),
    "review: blind pass": (28_000, 1_500),
    "review: deliberation": (14_000, 1_200),
    "review: critic": (40_000, 2_000),
    "review: revision": (42_000, 6_000),
}
PAGES_PER_TOOL_CALL = 1  # a search call returns several results; roughly one page each is summarized
PILOT = "Measured reference (Nov 17 pilot): $0.19 without review, $0.36 with a two-vendor panel."


@dataclass
class Stage:
    """One stage of the estimate."""

    name: str
    models: list[str]
    calls_low: int
    calls_high: int
    cost_low: float | None = None
    cost_high: float | None = None
    unpriced: list[str] = field(default_factory=list)


def _price(model: str, prices: dict[str, tuple[float, float]]) -> tuple[float, float] | None:
    from open_deep_research.bench import price_for

    return price_for(model, prices)


def stages(cfg: Any) -> list[Stage]:
    """Return the stages with low and high call counts for the settings in ``cfg``."""
    from open_deep_research.effort import limit_panel

    rounds = max(1, int(cfg.max_researcher_iterations))
    units = max(1, int(cfg.max_concurrent_research_units))
    tools = max(1, int(cfg.max_react_tool_calls))
    low_researchers, low_tools = min(2, units), min(3, tools)
    panel = [m.strip() for m in (cfg.review_models or "").split(",") if m.strip()]
    panel = limit_panel(panel, int(getattr(cfg, "review_panel_limit", 0) or 0))
    review = bool(getattr(cfg, "cross_vendor_review_enabled", True)) and len(panel) >= 1
    out = [
        Stage("clarify and brief", [cfg.research_model], 1 + bool(cfg.allow_clarification), 1 + bool(cfg.allow_clarification)),
        Stage("supervisor", [cfg.model_for("supervisor")], 1, rounds),
        Stage("researchers", [cfg.model_for("researcher")], low_researchers * low_tools, rounds * units * tools),
        Stage("page summaries", [cfg.model_for("summarization")], low_researchers * low_tools * PAGES_PER_TOOL_CALL,
              rounds * units * tools * PAGES_PER_TOOL_CALL),
        Stage("compression", [cfg.model_for("compression")], low_researchers, rounds * units),
        Stage("report", [cfg.model_for("final_report")], 1, 1),
    ]
    if review:
        n = len(panel)
        out.append(Stage("review: critiques and vote", panel, 2 * n, 2 * n))
        if getattr(cfg, "review_blind_pass_enabled", False):
            out.append(Stage("review: blind pass", panel, n, n))
        rounds_d = int(getattr(cfg, "review_deliberation_rounds", 0) or 0)
        if rounds_d:
            out.append(Stage("review: deliberation", panel, n, n * rounds_d))
        if getattr(cfg, "review_critic_enabled", False):
            out.append(Stage("review: critic", panel, n, n))  # each critique is checked by a panel model from another vendor
        out.append(Stage("review: revision", [cfg.review_reviser_model or cfg.model_for("final_report")], 1, 1))
    return out


def price_stages(items: list[Stage], prices: dict[str, tuple[float, float]] | None = None) -> list[Stage]:
    """Fill in costs; a stage whose model has no known price keeps ``None`` and lists the model."""
    prices = prices or {}
    for stage in items:
        tokens_in, tokens_out = TOKENS[stage.name]
        per_call = []
        for model in stage.models:
            price = _price(model, prices)
            if price is None:
                stage.unpriced.append(model)
            else:
                per_call.append(tokens_in * price[0] + tokens_out * price[1])
        if per_call and not stage.unpriced:
            mean = sum(per_call) / len(per_call)  # panel stages spread calls across the panel
            stage.cost_low, stage.cost_high = stage.calls_low * mean, stage.calls_high * mean
    return items


def render(items: list[Stage], effort: str = "") -> str:
    """Return the estimate as text."""
    lines = [f"Rough estimate for one run{f' (effort {effort})' if effort else ''}. No model was called.", "",
             f"{'stage':28} {'calls':>11} {'cost':>17}  model(s)"]
    low = high = 0.0
    missing: list[str] = []
    for s in items:
        calls = f"{s.calls_low}–{s.calls_high}" if s.calls_low != s.calls_high else str(s.calls_low)
        if s.cost_low is None:
            cost = "unknown price"
            missing += [m for m in s.unpriced if m not in missing]
        else:
            low, high = low + s.cost_low, high + (s.cost_high or 0)
            cost = f"${s.cost_low:.3f}–${s.cost_high:.3f}" if s.cost_low != s.cost_high else f"${s.cost_low:.3f}"
        lines.append(f"{s.name:28} {calls:>11} {cost:>17}  {', '.join(dict.fromkeys(s.models))}")
    priced = [s for s in items if s.cost_low is not None]
    if priced:
        lines += ["", f"total for priced stages: ${low:.2f} (low) to ${high:.2f} (every limit reached)"]
    else:
        lines += ["", "no stage could be priced"]
    if missing:
        lines.append("no price known for: " + ", ".join(missing) + " (run `crossvet setup` to cache OpenRouter's catalog)")
    lines += ["low = one supervisor round, two researchers, three tool calls each; high = every limit reached.",
              "Tokens per call are fixed assumptions (estimate.TOKENS), so treat this as a range, not a quote.", PILOT,
              "Hard stop: --max-usd or MAX_RUN_USD."]
    return "\n".join(lines) + "\n"
