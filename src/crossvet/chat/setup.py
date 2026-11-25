"""Write a first ``crossvet-chat.toml`` from the API keys you have.

Two sources, both only a starting point (``crossvet chat bench`` replaces guesses with measurements):

- **OpenRouter's public model list** (``--openrouter``): for each major vendor, general-purpose
  text models released in the last six months are sorted by price. The cheapest fills
  ``quick``; the newest model in the middle third fills ``balanced``; the newest in the top
  third fills ``strong``. An older version can cost more than its successor, so when the middle
  third holds a newer version of the same model (``claude-fable-5.2`` against ``claude-fable-5.1``),
  the newer version fills ``strong`` and the next newest in the middle third (or the same model)
  fills ``balanced``. Context windows and prices
  come from the list. Models that are not
  general chat models (image, audio, coding-only, safety classifiers, open-weight models,
  previews, "-pro" variants) are left out by name.
- **Direct vendor keys**: a small table of example model ids, dated below. Model names go
  stale, so check them with your vendor before relying on them.
"""

from __future__ import annotations

import os
import re
import time
from typing import Any

import httpx

from crossvet.chat import providers
from crossvet.chat.config import SLOT_HELP, SLOTS

OPENROUTER_MODELS_URL = "https://openrouter.ai/api/v1/models"
VENDORS = ("openai", "anthropic", "google", "x-ai")
RECENT_DAYS = 180     # prefer models released in the last six months...
MAX_AGE_DAYS = 400    # ...and widen to this when a vendor has fewer than three of those
# Not general-purpose chat models, judged by name. Checked against the live list on 2026-11-22.
SPECIAL = re.compile(r"(safeguard|guard|oss|gemma|codex|image|audio|preview|customtools|multi-agent|omni|banana|nano|"
                     r"chat-latest|embed|tts|realtime|search)|-pro$")

# Example ids for direct vendor keys, as used in this project's own runs in November 2026.
# quick, balanced, strong; prices are USD per million tokens (input, output) and are examples to verify.
EXAMPLES_DATE = "2026-11"
EXAMPLES: dict[str, list[tuple[str, float, float]]] = {
    "openai": [("openai:gpt-6-luna", 0.10, 0.50), ("openai:gpt-6.1-terra", 1.0, 5.0), ("openai:gpt-6.1-sol", 2.0, 10.0)],
    "anthropic": [("anthropic:claude-haiku-5-5", 0.10, 0.50), ("anthropic:claude-sonnet-5-5", 2.0, 10.0),
                  ("anthropic:claude-opus-5-5", 4.0, 20.0)],
}


def fetch_catalog(transport: httpx.BaseTransport | None = None) -> list[dict[str, Any]]:
    """OpenRouter's public list of models (no key needed)."""
    with httpx.Client(timeout=30, transport=transport) as client:
        response = client.get(OPENROUTER_MODELS_URL)
        response.raise_for_status()
        return list(response.json().get("data", []))


def _price(entry: dict[str, Any], key: str) -> float | None:
    try:
        return float(entry["pricing"][key]) * 1_000_000
    except (KeyError, TypeError, ValueError):
        return None


def _family(model: str) -> str:
    """Return the model name without version numbers: ``claude-fable-5.1`` and ``claude-fable-5.2`` match."""
    return re.sub(r"[\d.]+", "", model.rpartition("/")[2]).strip("-")


def _newest(rows: list[tuple[float, float, str]]) -> str:
    return max(rows, key=lambda item: item[1])[2]


def from_catalog(catalog: list[dict[str, Any]], now: float | None = None) -> tuple[dict[str, list[str]], dict[str, dict[str, Any]]]:
    """Fill the slots from OpenRouter's list; return ``(slots, models)``."""
    now = now or time.time()
    slots: dict[str, list[str]] = {name: [] for name in SLOTS}
    models: dict[str, dict[str, Any]] = {}
    per_vendor: dict[str, list[tuple[float, float, str]]] = {}
    for entry in catalog:
        model_id = str(entry.get("id", ""))
        vendor, _, name = model_id.partition("/")
        outputs = (entry.get("architecture") or {}).get("output_modalities") or ["text"]
        cost_in, cost_out = _price(entry, "prompt"), _price(entry, "completion")
        created = float(entry.get("created") or 0)
        if (vendor not in VENDORS or outputs != ["text"] or not cost_in or not cost_out or ":" in model_id
                or SPECIAL.search(name) or "tools" not in (entry.get("supported_parameters") or [])
                or now - created > MAX_AGE_DAYS * 86400):
            continue
        key = f"openrouter:{model_id}"
        per_vendor.setdefault(vendor, []).append((cost_in + cost_out, created, key))
        models[key] = {"context": int(entry.get("context_length") or 0), "input": round(cost_in, 4), "output": round(cost_out, 4)}
    used: set[str] = set()
    for vendor in VENDORS:
        everything = sorted(per_vendor.get(vendor, []))
        recent = [row for row in everything if now - row[1] <= RECENT_DAYS * 86400]
        ranked = recent if len(recent) >= 3 else everything
        if not ranked:
            continue
        third = max(1, len(ranked) // 3)
        middle = ranked[third: len(ranked) - third] or ranked
        picks = {"quick": ranked[0][2], "balanced": _newest(middle), "strong": _newest(ranked[len(ranked) - third:])}
        created = {row[2]: row[1] for row in ranked}
        if (created[picks["balanced"]] > created[picks["strong"]]
                and _family(picks["balanced"]) == _family(picks["strong"])):
            # an older version can cost more than its successor: strong takes the newer version
            picks["strong"] = picks["balanced"]
            rest = [row for row in middle if row[2] != picks["strong"]]
            picks["balanced"] = _newest(rest) if rest else picks["strong"]
        for slot, model in picks.items():
            if model not in slots[slot]:
                slots[slot].append(model)
            used.add(model)
    # fresh: xAI's models read X in real time; long: the largest context windows among the picks
    slots["fresh"] = [m for m in slots["strong"] + slots["balanced"] if providers.vendor_of(m) == "x-ai"][:1]
    slots["long"] = sorted(used, key=lambda m: -models[m]["context"])[:2]
    main_vendor = providers.vendor_of(slots["strong"][0]) if slots["strong"] else ""
    slots["reviewer"] = [m for m in slots["strong"] if providers.vendor_of(m) != main_vendor][:2]
    return slots, {m: v for m, v in models.items() if m in used}


def from_env() -> tuple[dict[str, list[str]], dict[str, dict[str, Any]]]:
    """Fill the slots from the example table, for the direct vendor keys that are set."""
    slots: dict[str, list[str]] = {name: [] for name in SLOTS}
    models: dict[str, dict[str, Any]] = {}
    for vendor, rows in EXAMPLES.items():
        if not providers.available(vendor):
            continue
        for slot, (model, cost_in, cost_out) in zip(("quick", "balanced", "strong"), rows, strict=True):
            slots[slot].append(model)
            models[model] = {"context": 0, "input": cost_in, "output": cost_out}
    strong = slots["strong"]
    slots["reviewer"] = strong[1:2] if len(strong) > 1 else []
    return slots, models


def render(slots: dict[str, list[str]], models: dict[str, dict[str, Any]], note: str) -> str:
    """Return the config file as text."""
    lines = [
        "# crossvet chat configuration. API keys are NOT stored here: they are read from the environment (.env.example).",
        f"# {note}",
        "# Each slot is an ordered list: the first model is tried first, the next only when it fails a check.",
        "",
        "[slots]",
    ]
    for name in SLOTS:
        lines.append(f"# {name}: {SLOT_HELP[name]}")
        lines.append(f"{name} = [" + ", ".join(f'"{m}"' for m in slots.get(name, [])) + "]")
    lines += [
        "",
        "# Which slot each kind of task starts in. Kinds: quick, summarize, extract, translate, writing, general,",
        "# code, reasoning, review, fresh. Hard tasks move up automatically.",
        "[routes]",
        "# code = \"strong\"",
        "",
        "[limits]",
        "max_usd_per_day = 5.0     # 0 = no cap",
        "max_usd_per_call = 0.50   # worst-case estimate before a call; needs prices below",
        "max_output_tokens = 4000",
        "",
        "[memory]",
        "chars = 6000              # how much shared memory a model is shown",
        "history_turns = 12",
        "",
        "# context = context window in tokens (0 = unknown); input/output = USD per million tokens.",
    ]
    for model, info in models.items():
        lines.append(f'[models."{model}"]')
        lines.append(f"context = {info['context']}")
        lines.append(f"input = {info['input']}")
        lines.append(f"output = {info['output']}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def build(use_openrouter: bool, transport: httpx.BaseTransport | None = None) -> tuple[str, list[str]]:
    """Return the config text and a list of plain-language notes about what was done."""
    notes: list[str] = []
    if use_openrouter:
        slots, models = from_catalog(fetch_catalog(transport))
        note = f"Written {time.strftime('%Y-%m-%d')} from OpenRouter's model list, by price and release date. A starting point: check it."
        if not os.environ.get("OPENROUTER_API_KEY"):
            notes.append("OPENROUTER_API_KEY is not set yet: add it before asking anything.")
    else:
        slots, models = from_env()
        note = f"Written {time.strftime('%Y-%m-%d')} from example model ids dated {EXAMPLES_DATE}. Model names go stale: check them."
        if not models:
            notes.append("No OPENAI_API_KEY or ANTHROPIC_API_KEY found: the slots are empty. Add models by hand, or use --openrouter.")
    empty = [s for s in ("quick", "balanced", "strong") if not slots[s]]
    if empty and models:
        notes.append(f"Empty slots: {', '.join(empty)}.")
    if not slots["reviewer"]:
        notes.append("The reviewer slot is empty: `crossvet chat challenge` needs a model from a second vendor.")
    if not slots["fresh"]:
        notes.append("The fresh slot is empty: questions about current events go to the balanced slot.")
    return render(slots, models, note), notes
