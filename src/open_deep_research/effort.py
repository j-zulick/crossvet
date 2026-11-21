"""Effort tiers: how much work one run does, chosen in code.

``EFFORT=quick|standard|deep`` (or ``--effort`` on ``crossvet research`` and ``crossvet try``) sets
how deep the research goes and how much review runs. A setting you set yourself always wins over
the tier. ``--effort auto`` picks the tier from the question with the rules in ``classify``; no
model is asked. The numbers are starting points, not measured optima (design decision 26).
"""

from __future__ import annotations

import re
from typing import Any

# Settings each tier fills in when you have not set them. "standard" changes nothing.
TIERS: dict[str, dict[str, Any]] = {
    "quick": {
        "max_concurrent_research_units": 2,
        "max_researcher_iterations": 2,
        "max_react_tool_calls": 4,
        "review_panel_limit": 2,
        "review_deliberation_rounds": 0,
        "review_blind_pass_enabled": False,
    },
    "standard": {},
    "deep": {
        "max_researcher_iterations": 8,
        "max_react_tool_calls": 15,
        "review_deliberation_rounds": 2,
        "review_blind_pass_enabled": True,
    },
}
CHOICES = (*TIERS, "auto")

_DEEP_WORDS = re.compile(
    r"\b(compar\w+|versus|vs\.?|trade-?offs?|pros and cons|comprehensive|in[- ]depth|survey|literature|"
    r"evaluate|evaluation|analy[sz]e|analysis|landscape|strategy|roadmap|history of|timeline)\b", re.IGNORECASE)
_LOOKUP_START = re.compile(
    r"^\s*(who|what|when|where|which|is|are|was|were|does|do|did|how (many|much|old|long|tall|far))\b", re.IGNORECASE)
_LIST_ITEM = re.compile(r"(?m)^\s*(?:[-*•]|\d+[.)])\s+\S")
QUICK_MAX_CHARS = 120
DEEP_MIN_CHARS = 400


def classify(question: str) -> tuple[str, str]:
    """Pick a tier for a question from its text alone; return ``(tier, reason)``.

    Deep: long, several sub-questions, or wording that asks for a comparison or an analysis.
    Quick: one short lookup question. Anything else, and anything unclear, is standard, so a
    wrong guess never gives less research than the default.
    """
    text = (question or "").strip()
    parts = text.count("?") + len(_LIST_ITEM.findall(text))
    deep_word = _DEEP_WORDS.search(text)
    if len(text) >= DEEP_MIN_CHARS:
        return "deep", f"the question is long ({len(text)} characters)"
    if parts >= 3:
        return "deep", f"it has {parts} sub-questions"
    if deep_word:
        return "deep", f'it asks for a comparison or analysis ("{deep_word.group(0)}")'
    if text and len(text) <= QUICK_MAX_CHARS and parts <= 1 and _LOOKUP_START.match(text):
        return "quick", "it is one short lookup question"
    return "standard", "it is neither a short lookup nor a multi-part or analytical question"


def normalize(value: str | None) -> str:
    """Return a tier name, or ``""`` when the value is empty, ``auto`` or unknown."""
    tier = (value or "").strip().lower()
    return tier if tier in TIERS else ""


def apply(values: dict[str, Any]) -> dict[str, Any]:
    """Fill a settings dict with its tier's values, leaving every setting already present alone."""
    tier = normalize(values.get("effort"))
    return {**TIERS.get(tier, {}), **values}


def limit_panel(models: list[str], limit: int) -> list[str]:
    """Keep at most ``limit`` reviewers (0 = all), taking one per vendor first, in the order given."""
    if limit <= 0 or len(models) <= limit:
        return models
    from open_deep_research.models import maker_of

    picked: list[str] = []
    seen: set[str] = set()
    for model in models:  # first pass: one model per vendor
        if len(picked) < limit and maker_of(model) not in seen:
            picked.append(model)
            seen.add(maker_of(model))
    for model in models:  # second pass: fill up when there are fewer vendors than seats
        if len(picked) < limit and model not in picked:
            picked.append(model)
    return [m for m in models if m in picked]


def describe(configurable: Any) -> str:
    """One line for the Review notes: the tier and the values in effect for what it governs."""
    tier = normalize(getattr(configurable, "effort", "")) or "standard"
    panel = getattr(configurable, "review_panel_limit", 0)
    return (
        f"Effort: {tier} ({configurable.max_concurrent_research_units} parallel researchers, "
        f"{configurable.max_researcher_iterations} research rounds, {configurable.max_react_tool_calls} tool calls each, "
        f"{'panel of ' + str(panel) if panel else 'full panel'}, "
        f"{configurable.review_deliberation_rounds} deliberation round(s), "
        f"blind pass {'on' if configurable.review_blind_pass_enabled else 'off'})"
    )
