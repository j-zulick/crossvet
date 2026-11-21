"""Python API: run Crossvet from your own code.

    from open_deep_research.api import run, ask, review

    result = run("How did JWST's mirror design solve the launch problem?",
                 config={"context_pack": "seo", "review_deliberation_rounds": 2})
    print(result["final_report"])          # the reviewed report
    print(result["review"]["status"])      # review details, as in the run export
    print(ask("Which source gives the mirror's diameter?", result)["answer"])

``run`` / ``arun`` take any setting from ``Configuration`` in ``config`` (environment
variables still apply underneath). ``edition="deep_agent"`` runs the Deep Agents edition.
Human approval is skipped: API runs are unattended. ``review`` / ``areview`` run the
cross-vendor review on an existing report against files or URLs you give it.
"""

from __future__ import annotations

import asyncio
import uuid
from typing import Any

from langchain_core.messages import HumanMessage

EDITIONS = ("deep_researcher", "deep_agent")


def _graph(edition: str) -> Any:
    if edition == "deep_researcher":
        from open_deep_research.deep_researcher import deep_researcher

        return deep_researcher
    if edition == "deep_agent":
        from open_deep_research.deep_agent import deep_agent

        return deep_agent
    raise ValueError(f"edition must be one of {EDITIONS}")


async def arun(question: str, config: dict[str, Any] | None = None, edition: str = "deep_researcher", thread_id: str | None = None) -> dict[str, Any]:
    """Research ``question`` and return the final state: ``final_report``, ``review``, ``raw_notes`` and the rest."""
    if not question or not question.strip():
        raise ValueError("question is empty")
    configurable = {"require_approval": False, **(config or {})}
    run_config = {"configurable": {**configurable, "thread_id": thread_id or uuid.uuid4().hex[:12]}}
    return await _graph(edition).ainvoke({"messages": [HumanMessage(content=question.strip())]}, run_config)


def run(question: str, config: dict[str, Any] | None = None, edition: str = "deep_researcher", thread_id: str | None = None) -> dict[str, Any]:
    """Blocking version of :func:`arun` (not for use inside a running event loop)."""
    return asyncio.run(arun(question, config, edition, thread_id))


async def aask(question: str, result: dict[str, Any], model: str | None = None) -> dict[str, Any]:
    """Answer a follow-up from a finished run's notes: ``answer``, ``flagged_urls``, ``covered``."""
    from open_deep_research.configuration import Configuration
    from open_deep_research.followup import answer, model_asker

    cfg = Configuration.from_runnable_config({"configurable": {}})
    return await answer(question, result, model_asker(model or cfg.final_report_model, cfg.final_report_model_max_tokens))


def ask(question: str, result: dict[str, Any], model: str | None = None) -> dict[str, Any]:
    """Blocking version of :func:`aask`."""
    return asyncio.run(aask(question, result, model))


async def areview(report: str, sources: list[str], brief: str = "", config: dict[str, Any] | None = None) -> dict[str, Any]:
    """Review an existing ``report`` against ``sources`` (file paths or http(s) URLs)."""
    from open_deep_research.review_doc import areview as _areview

    return await _areview(report, sources, brief, config)


def review(report: str, sources: list[str], brief: str = "", config: dict[str, Any] | None = None) -> dict[str, Any]:
    """Blocking version of :func:`areview`."""
    return asyncio.run(areview(report, sources, brief, config))
