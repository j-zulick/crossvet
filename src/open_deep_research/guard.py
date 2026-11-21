"""The model guard: code that decides when a stronger model is used and when a run must stop.

Two parts, both off until you set them:

- **Escalation** (``ESCALATION_MODEL``): a stage runs on its own (cheaper) model first. Only when
  that call fails after its retries (an error, or structured output that does not parse) is the
  same call sent to the escalation model. Each escalation is recorded and listed in the Review
  notes. Review roles are never escalated: the panel's vendor mix is the user's choice.
- **Spend cap** (``MAX_RUN_USD``): a callback adds up what each model call cost and stops the run
  before the next call once the cap is reached. A stage that handles its own errors may still
  finish with what it has, so a capped run can end with a partial report; the CLI says so. Cost is the figure the provider reports
  (OpenRouter), else tokens times the list price in the OpenRouter catalog; calls whose price is
  unknown are counted in ``unpriced_calls`` and cannot be capped.

No model takes part in either decision.
"""

from __future__ import annotations

import logging
from collections import OrderedDict
from typing import Any
from uuid import UUID

from langchain_core.callbacks import AsyncCallbackHandler
from langchain_core.runnables import RunnableLambda

logger = logging.getLogger(__name__)

MAX_THREADS_REMEMBERED = 200
# thread id -> ["<role>: <model> → <escalation model> (<error type>)", ...]
_ESCALATIONS: OrderedDict[str, list[str]] = OrderedDict()


def _thread(config: Any) -> str:
    return str(((config or {}).get("configurable") or {}).get("thread_id") or "")


def record_escalation(thread: str, role: str, model: str, stronger: str, reason: str) -> None:
    """Remember one escalation for the run's Review notes, and log it."""
    line = f"{role}: {model} → {stronger} ({reason})"
    logger.warning("escalated %s", line)
    _ESCALATIONS.setdefault(thread, []).append(line)
    _ESCALATIONS.move_to_end(thread)
    while len(_ESCALATIONS) > MAX_THREADS_REMEMBERED:
        _ESCALATIONS.popitem(last=False)


def escalations(config: Any) -> list[str]:
    """Escalations recorded for the run this config belongs to."""
    return list(_ESCALATIONS.get(_thread(config), []))


def with_escalation(primary: Any, stronger: Any, role: str, model: str, stronger_name: str) -> Any:
    """Return a runnable that calls ``primary`` and, only if that raises, calls ``stronger``."""

    async def acall(value: Any, config: Any = None) -> Any:
        try:
            return await primary.ainvoke(value, config)
        except Exception as exc:  # the stage's own retries are already spent
            record_escalation(_thread(config), role, model, stronger_name, type(exc).__name__)
            return await stronger.ainvoke(value, config)

    def call(value: Any, config: Any = None) -> Any:
        try:
            return primary.invoke(value, config)
        except Exception as exc:
            record_escalation(_thread(config), role, model, stronger_name, type(exc).__name__)
            return stronger.invoke(value, config)

    return RunnableLambda(call, afunc=acall, name=f"{role}_with_escalation")


def escalation_target(model: str, escalation_model: str) -> str:
    """Return the model to escalate to, or ``""`` when escalation is off or would change nothing."""
    target = (escalation_model or "").strip()
    return "" if not target or target == model else target


class BudgetExceeded(RuntimeError):
    """The run reached its spend cap (``MAX_RUN_USD``)."""


class BudgetGuard(AsyncCallbackHandler):
    """Add up the cost of model calls and refuse the next call once the cap is reached."""

    raise_error = True  # LangChain swallows callback errors unless this is set

    def __init__(self, max_usd: float) -> None:  # noqa: D107
        self.max_usd = float(max_usd)
        self.spent = 0.0
        self.unpriced_calls = 0
        self.tripped = False
        self._models: dict[UUID, str] = {}

    async def on_chat_model_start(self, serialized: dict[str, Any], messages: Any, *, run_id: UUID, **kwargs: Any) -> None:  # noqa: D102
        if self.max_usd > 0 and self.spent >= self.max_usd:
            self.tripped = True
            raise BudgetExceeded(f"spend cap reached: ${self.spent:.2f} of MAX_RUN_USD=${self.max_usd:.2f}; no further model calls were made")
        params = kwargs.get("invocation_params") or {}
        meta = kwargs.get("metadata") or {}
        name = str(params.get("model") or params.get("model_name") or meta.get("ls_model_name") or "")
        provider = str(meta.get("ls_provider") or "")
        self._models[run_id] = f"{provider}:{name}" if provider and ":" not in name else name

    async def on_llm_end(self, response: Any, *, run_id: UUID, **kwargs: Any) -> None:  # noqa: D102
        model = self._models.pop(run_id, "")
        for gens in getattr(response, "generations", []) or []:
            for gen in gens:
                message = getattr(gen, "message", None)
                if message is not None:
                    self._add(model, message)

    def _add(self, model: str, message: Any) -> None:
        from open_deep_research.bench import price_for
        from open_deep_research.models import cost_of

        reported = cost_of(message)
        if reported is not None:
            self.spent += reported
            return
        usage = getattr(message, "usage_metadata", None) or {}
        price = price_for(model, {}) if model else None
        if price is None:
            self.unpriced_calls += 1
            return
        self.spent += int(usage.get("input_tokens", 0) or 0) * price[0] + int(usage.get("output_tokens", 0) or 0) * price[1]

    def summary(self) -> str:
        """One line for the terminal after a run."""
        text = f"spend counted: ${self.spent:.2f}" + (f" of a ${self.max_usd:.2f} cap" if self.max_usd > 0 else "")
        return text + (f"; {self.unpriced_calls} call(s) had no known price and are not included" if self.unpriced_calls else "")


def budget_callbacks(max_usd: float) -> list[Any]:
    """Callbacks to add to a run: a ``BudgetGuard`` when a cap is set, nothing otherwise."""
    return [BudgetGuard(max_usd)] if max_usd and max_usd > 0 else []
