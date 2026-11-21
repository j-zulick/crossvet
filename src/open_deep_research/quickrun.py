"""Run one research question end to end and save everything needed to judge the run.

    uv run crossvet-try                          # a default question with checkable facts
    uv run crossvet-try "Your question" --out first-run

Writes to ``<out>/<timestamp>/``:

- ``report.md``   the final report (with Review notes when review is on)
- ``review.json`` the review summary (reviewers, scores, flagged URLs, critic, failures)
- ``run.json``    models and settings used, duration, outcome (no keys)
- ``share.md``    a short summary that is safe to paste into a chat or an issue

Approval is skipped so the run never waits for input.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import platform
import sys
import time
import traceback
from datetime import datetime
from importlib import metadata
from pathlib import Path
from typing import Any

DEFAULT_QUESTION = (
    "What is the James Webb Space Telescope's primary mirror made of, how large is it, "
    "and when and from where was the telescope launched?"
)
SHOWN_SETTINGS = (
    "SEARCH_API", "RESEARCH_MODEL", "SUMMARIZATION_MODEL", "COMPRESSION_MODEL", "FINAL_REPORT_MODEL",
    "CROSS_VENDOR_REVIEW_ENABLED", "REVIEW_MODELS", "REVIEW_REVISER_MODEL", "REVIEW_CRITIC_ENABLED",
    "REVIEW_DELIBERATION_ROUNDS", "EFFORT", "MAX_RESEARCHER_ITERATIONS", "MAX_REACT_TOOL_CALLS", "REVIEW_PANEL_LIMIT",
    "ESCALATION_MODEL", "MAX_RUN_USD",
)


def _version(pkg: str) -> str:
    try:
        return metadata.version(pkg)
    except metadata.PackageNotFoundError:
        return "?"


def settings() -> dict[str, str]:
    """Model and review settings in effect (never keys)."""
    from open_deep_research.configuration import Configuration

    cfg = Configuration.from_runnable_config({"configurable": {}})
    out = {}
    for var in SHOWN_SETTINGS:
        field = var.lower()
        if field in Configuration.model_fields:
            value = getattr(cfg, field)
            out[var] = getattr(value, "value", value)
    return {k: str(v) for k, v in out.items()}


def share_text(question: str, run: dict[str, Any], review: dict[str, Any], report: str) -> str:
    """Short, key-free summary of a run."""
    notes = report.split("## Review notes", 1)[1].strip() if "## Review notes" in report else "(review off or skipped)"
    lines = [
        f"# Crossvet run {run['started_at']}",
        f"- Question: {question}",
        f"- Outcome: {run['outcome']} in {run['seconds']} s",
        f"- crossvet {run['versions']['crossvet']} · langgraph {run['versions']['langgraph']} · Python {run['versions']['python']}",
        *[f"- {k}: {v}" for k, v in run["settings"].items()],
        f"- Review status: {review.get('status', 'off')}",
    ]
    if run.get("error"):
        lines.append(f"- Error: {run['error']}")
    return "\n".join(lines) + "\n\n## Review notes\n\n" + notes + "\n"


def _tracing() -> Any:
    """Langfuse tracing module when this version has it, else None."""
    try:
        from open_deep_research import tracing  # added in v0.3
    except ImportError:
        return None
    return tracing


async def _invoke(question: str, budget: list[Any] | None = None) -> dict[str, Any]:
    from langchain_core.messages import HumanMessage

    from open_deep_research.deep_researcher import deep_researcher

    tracing = _tracing()
    callbacks = [*(tracing.get_callbacks() if tracing else []), *(budget or [])]
    config = {"recursion_limit": 200, "callbacks": callbacks, "metadata": {"langfuse_tags": ["crossvet-try"]} if callbacks else {}}
    try:
        return await deep_researcher.ainvoke({"messages": [HumanMessage(content=question)]}, config)
    finally:
        if tracing:
            tracing.flush()


def main(argv: list[str] | None = None, invoke: Any = None) -> int:
    """Command-line entry point."""
    from dotenv import load_dotenv

    p = argparse.ArgumentParser(prog="crossvet-try", description="Run one question and save the report, review and a shareable summary.")
    p.add_argument("question", nargs="?", default=DEFAULT_QUESTION)
    p.add_argument("--out", default="first-run", help="output folder (default first-run)")
    p.add_argument("--effort", choices=("quick", "standard", "deep", "auto"), help="how much work the run does (default: EFFORT, else standard); auto picks from the question, in code")
    p.add_argument("--max-usd", type=float, help="stop before the next model call once this much is spent (default: MAX_RUN_USD; 0 = no cap)")
    args = p.parse_args(argv)
    load_dotenv()
    os.environ["REQUIRE_APPROVAL"] = "false"
    os.environ["ALLOW_CLARIFICATION"] = "false"
    from open_deep_research.cli import set_run_limits

    budget = set_run_limits(args.effort, args.max_usd, args.question)

    started = datetime.now().astimezone()
    folder = Path(args.out) / started.strftime("%Y%m%dT%H%M%S")
    folder.mkdir(parents=True, exist_ok=True)
    sys.stderr.write(f"Researching: {args.question}\n(this usually takes a few minutes)\n")
    t0 = time.perf_counter()
    out: dict[str, Any] = {}
    error = ""
    try:
        out = asyncio.run(invoke(args.question) if invoke else _invoke(args.question, budget))
    except Exception as exc:
        error = f"{type(exc).__name__}: {str(exc)[:500]}"
        (folder / "traceback.txt").write_text(traceback.format_exc(), encoding="utf-8")
    report = out.get("final_report") or ""
    review = out.get("review") or {}
    failed_report = report.startswith("Error generating final report")
    run = {
        "started_at": started.isoformat(timespec="seconds"),
        "seconds": round(time.perf_counter() - t0, 1),
        "outcome": "error" if error or failed_report or not report else "ok",
        "error": error or (report[:300] if failed_report else ""),
        "settings": settings(),
        "versions": {"crossvet": _version("crossvet"), "langgraph": _version("langgraph"), "python": platform.python_version()},
    }
    (folder / "report.md").write_text(report, encoding="utf-8")
    (folder / "review.json").write_text(json.dumps(review, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    (folder / "run.json").write_text(json.dumps(run, indent=2), encoding="utf-8")
    (folder / "share.md").write_text(share_text(args.question, run, review, report), encoding="utf-8")
    sys.stdout.write((folder / "share.md").read_text(encoding="utf-8"))
    sys.stdout.write(f"\nSaved to {folder}/ (report.md, review.json, run.json, share.md)\n")
    return 0 if run["outcome"] == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main())
