"""Support checks: does a quoted passage actually support what is claimed from it?

Crossvet's code checks that a quote appears verbatim in the research notes. That stops
invented quotes, but not real quotes used for the wrong claim. With
``REVIEW_SUPPORT_CHECKER=jev``, every claim that leans on a passage is also put to
**Jev**, TypeSafe's decision model: a Noul question ("does `passage` support `claim`?")
answered with a probability. It runs before a change is applied, so it gates:

- deliberation position changes (a revision or withdrawal and its passage);
- challengers' AGREE endorsements (counted as grounded only when supported) and BUILD_ON
  additions (applied only when supported);
- blind-pass points (a point counts only when its passage supports it).

The verbatim-quote check stays the first gate; Jev only narrows what passes it. If a
Jev call fails, that claim is judged by the quote check alone and the failure is
counted. Results (probability, model id) are kept in the review log and export.
"""

from __future__ import annotations

import asyncio
import os
from typing import Any, Protocol

QUESTION = (
    "Does `passage` state or directly imply `claim`? Answer yes only when the passage itself "
    "supports the claim, not when it is merely on the same topic."
)
CRITERIA = {
    "true": "The passage states the claim or something that directly implies it.",
    "false": "The passage is unrelated, only on the same topic, contradicts the claim, or supports only part of it.",
}


class SupportChecker(Protocol):
    """Anything that scores (claim, passage) pairs with a probability of support (None = unknown)."""

    model: str
    errors: int

    async def check(self, pairs: list[tuple[str, str]]) -> list[float | None]:  # pragma: no cover - protocol
        """Return one probability (or None) per pair, in order."""
        ...


class JevChecker:
    """Support checks with Jev through the TypeSafe Python SDK (``typesafe-sdk``)."""

    def __init__(self, model: str = "", client: Any | None = None, concurrency: int = 8, timeout: float = 10.0):
        """Use ``client`` (an ``AsyncTypeSafeClient``-like object) or build one from TYPESAFE_* settings."""
        self.model = model or os.getenv("TYPESAFE_DEFAULT_MODEL", "") or "jev-latest"
        self._client = client
        self._sem = asyncio.Semaphore(max(1, concurrency))
        self._timeout = timeout
        self.errors = 0
        self.served_by: set[str] = set()

    def _get_client(self) -> Any:
        if self._client is None:
            from typesafe_sdk import AsyncTypeSafeClient

            self._client = AsyncTypeSafeClient(model=self.model, timeout=self._timeout)
        return self._client

    async def _one(self, claim: str, passage: str) -> float | None:
        async with self._sem:
            try:
                resp = await self._get_client().system_one(
                    state={"claim": claim[:2000], "passage": passage[:4000]},
                    questions={"supported": {"type": "noul", "instructions": QUESTION, "criteria": CRITERIA}},
                    model=self.model,
                )
                answer = resp.answers["supported"]
                if getattr(resp, "model", ""):
                    self.served_by.add(resp.model)
                return float(answer.noul)
            except Exception:
                self.errors += 1
                return None

    async def check(self, pairs: list[tuple[str, str]]) -> list[float | None]:
        """Score every (claim, passage) pair in parallel (bounded); failures give None."""
        return list(await asyncio.gather(*(self._one(c, p) for c, p in pairs)))


def build_checker(name: str, model: str = "") -> SupportChecker | None:
    """Return the configured checker, or None when support checks are off."""
    name = (name or "").strip().lower()
    if name in ("", "none", "off", "false"):
        return None
    if name == "jev":
        if not os.getenv("TYPESAFE_API_KEY"):
            raise RuntimeError("REVIEW_SUPPORT_CHECKER=jev needs TYPESAFE_API_KEY (from console.typesafe.ai)")
        return JevChecker(model=model)
    raise ValueError(f"Unknown REVIEW_SUPPORT_CHECKER {name!r}; use 'jev' or leave it empty")


async def score_pairs(checker: SupportChecker | None, pairs: list[tuple[str, str]]) -> dict[tuple[str, str], float | None]:
    """Score unique pairs once; empty dict when there is no checker."""
    if checker is None or not pairs:
        return {}
    unique = list(dict.fromkeys(pairs))
    return dict(zip(unique, await checker.check(unique)))


def passes(prob: float | None, min_prob: float) -> bool:
    """Return False only for a real score below ``min_prob``; a missing score never blocks."""
    return prob is None or prob >= min_prob
