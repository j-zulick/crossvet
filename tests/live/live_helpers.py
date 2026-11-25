"""Helpers for the live tests: real API calls with the keys in `.env`. They run only with CROSSVET_LIVE=1, so nobody spends money by accident.

    CROSSVET_LIVE=1 uv run pytest tests/live -q

Every test uses a real task from used-car dealer work in Sarasota, Florida, and writes one line per
answer to ``CROSSVET_LIVE_LOG`` (default ``live-run.jsonl``): the test, model, kind, slot, reason,
tokens, cost and seconds. ``docs/live-runs/`` is written from that file. Spend is capped by the
settings below (USD 3 a day, USD 0.50 a call).
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

from crossvet.chat import providers
from crossvet.chat.cli import load_env

load_env(os.environ.get("CROSSVET_ENV_FILE", ".env"))

# Model ids your keys could call on 2026-11-25 (listed from each vendor's models endpoint).
# Prices are USD per million tokens (input, output), from this project's November 2026 settings.
MODELS = {
    "openai:gpt-6-luna": (0.10, 0.50),
    "openai:gpt-6.1-terra": (1.0, 5.0),
    "openai:gpt-6.1-sol": (2.0, 10.0),
    "anthropic:claude-haiku-5-5": (0.10, 0.50),
    "anthropic:claude-sonnet-5-5": (2.0, 10.0),
    "anthropic:claude-opus-5-5": (4.0, 20.0),
}


def have(provider: str) -> bool:
    """Whether this provider's key is set."""
    return providers.available(provider)


def settings(**limits: float) -> dict:
    """Slots filled with the models above whose keys are set."""
    usable = [m for m in MODELS if have(m.split(":", 1)[0])]
    pick = lambda *names: [n for n in names if n in usable]  # noqa: E731
    slots = {
        "quick": pick("openai:gpt-6-luna", "anthropic:claude-haiku-5-5"),
        "balanced": pick("anthropic:claude-sonnet-5-5", "openai:gpt-6.1-terra"),
        "strong": pick("anthropic:claude-opus-5-5", "openai:gpt-6.1-sol"),
        "fresh": pick("openai:gpt-6.1-terra", "anthropic:claude-sonnet-5-5"),
        "long": pick("anthropic:claude-sonnet-5-5", "openai:gpt-6.1-terra"),
        "vision": pick("openai:gpt-6.1-terra", "anthropic:claude-sonnet-5-5"),
        "reviewer": pick("openai:gpt-6.1-sol", "anthropic:claude-opus-5-5"),
    }
    return {
        "slots": slots,
        "limits": {"max_usd_per_day": 3.0, "max_usd_per_call": 0.5, "max_output_tokens": 4000, "timeout_seconds": 120,
                   **limits},
        "models": {m: {"context": 200_000, "input": i, "output": o} for m, (i, o) in MODELS.items()},
    }


LOG = Path(os.environ.get("CROSSVET_LIVE_LOG", "live-run.jsonl"))


def log(test: str, answer=None, **extra) -> None:
    """Append one line about an answer (or a check) to the live-run log."""
    row = {"test": test, "time": time.strftime("%Y-%m-%dT%H:%M:%S%z")}
    if answer is not None:
        row.update(model=answer.model, kind=answer.decision.task.kind, slot=answer.decision.slot,
                   why=answer.decision.explain(), input_tokens=answer.input_tokens, output_tokens=answer.output_tokens,
                   cost_usd=answer.cost, attempts=[(a.model, a.ok, a.problem, round(a.seconds, 2)) for a in answer.attempts],
                   answer_start=answer.text[:300])
    row.update(extra)
    with LOG.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row) + "\n")
