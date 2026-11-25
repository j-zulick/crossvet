"""Command-line runner with durable checkpoints.

Every step of a run is checkpointed, so a crashed or interrupted run resumes where it
stopped instead of starting over (and paying for completed model calls again).

    crossvet run "question" [--thread ID] [--auto-approve] [--out report.md]
    crossvet resume --thread ID [--auto-approve] [--out report.md]
    crossvet status --thread ID
    crossvet sessions [--limit 20]
    crossvet ask --thread ID "follow-up question" [--out FILE]

Checkpoints go to a local SQLite file by default (CROSSVET_CHECKPOINTS, default
.crossvet/checkpoints.sqlite). Set DATABASE_URL=postgresql://... to use Postgres
instead (install with: uv sync --extra postgres).
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, AsyncIterator, Callable

from open_deep_research.envfile import load_env

DEFAULT_SQLITE = ".crossvet/checkpoints.sqlite"

Approver = Callable[[dict[str, Any]], Any]


@asynccontextmanager
async def open_checkpointer(url: str | None = None) -> AsyncIterator[Any]:
    """Yield an async checkpointer: Postgres when url is postgres://..., else SQLite."""
    url = url if url is not None else os.getenv("DATABASE_URL", "")
    if url.startswith(("postgres://", "postgresql://")):
        try:
            from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
        except ImportError as exc:  # pragma: no cover - depends on optional extra
            raise SystemExit("Postgres checkpoints need: uv sync --extra postgres") from exc
        async with AsyncPostgresSaver.from_conn_string(url) as saver:
            await saver.setup()
            yield saver
        return
    from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

    path = url or os.getenv("CROSSVET_CHECKPOINTS", DEFAULT_SQLITE)
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    async with AsyncSqliteSaver.from_conn_string(path) as saver:
        yield saver


def auto_approve(_request: dict[str, Any]) -> dict[str, Any]:
    """Approve every pause without asking."""
    return {"decisions": [{"type": "approve"}]}


def interactive_approve(request: dict[str, Any]) -> dict[str, Any]:
    """Ask on the terminal: approve, reject, or type instructions."""
    action = (request.get("action_requests") or [{}])[0]
    args = action.get("args", {})
    print("\n=== Research complete: approval needed ===")
    print(f"Brief: {args.get('research_brief', '')[:800]}")
    print(f"Sources found: {args.get('sources_found', '?')}")
    preview = args.get("findings_preview", "")
    if preview:
        print(f"\nFindings preview:\n{preview[:1200]}\n")
    answer = input("[a]pprove, [r]eject, or type instructions for the report: ").strip()
    if answer.lower() in ("", "a", "approve", "y", "yes"):
        return {"decisions": [{"type": "approve"}]}
    if answer.lower() in ("r", "reject", "n", "no"):
        return {"decisions": [{"type": "reject", "message": "Rejected at the terminal."}]}
    edited = {"name": action.get("name", ""), "args": {**args, "instructions": answer}}
    return {"decisions": [{"type": "edit", "edited_action": edited}]}


async def drive(graph: Any, first_input: Any, thread_id: str, approver: Approver, callbacks: list[Any] | None = None, max_pauses: int = 10) -> dict[str, Any]:
    """Run a checkpointed graph to completion, answering interrupts with ``approver``.

    ``first_input`` of None resumes the thread from its last checkpoint.
    """
    config: dict[str, Any] = {"configurable": {"thread_id": thread_id}}
    if callbacks:
        config["callbacks"] = callbacks
    payload = first_input
    for _ in range(max_pauses + 1):
        result = await graph.ainvoke(payload, config)
        interrupts = result.get("__interrupt__") if isinstance(result, dict) else None
        if not interrupts:
            return result
        from langgraph.types import Command

        payload = Command(resume=approver(interrupts[0].value))
    raise RuntimeError(f"More than {max_pauses} pauses in one run; stopping.")


async def list_threads(saver: Any, limit: int = 20) -> list[dict[str, Any]]:
    """Threads in the checkpoint store, most recently updated first: thread id, last update, checkpoints."""
    threads: dict[str, dict[str, Any]] = {}
    async for item in saver.alist(None):
        tid = item.config["configurable"]["thread_id"]
        ts = item.checkpoint.get("ts", "")
        t = threads.setdefault(tid, {"thread": tid, "updated": ts, "checkpoints": 0})
        t["checkpoints"] += 1
        t["updated"] = max(t["updated"], ts)
    return sorted(threads.values(), key=lambda t: t["updated"], reverse=True)[:limit]


def _compile(saver: Any) -> Any:
    from open_deep_research.deep_researcher import deep_researcher_builder

    return deep_researcher_builder.compile(checkpointer=saver)


def _write_report(result: dict[str, Any], out: str | None) -> None:
    report = result.get("final_report") or "(no report produced)"
    if out:
        with open(out, "w", encoding="utf-8") as fh:
            fh.write(report)
        print(f"Report written to {out}")
    else:
        print(report)


def _estimate(args: argparse.Namespace) -> int:
    """Print the cost estimate for a run with the settings in force; call no model."""
    from open_deep_research import estimate
    from open_deep_research.configuration import Configuration

    set_run_limits(args.effort, None, args.question)
    cfg = Configuration.from_runnable_config({"configurable": {}})
    print(estimate.render(estimate.price_stages(estimate.stages(cfg)), os.environ.get("EFFORT", "")))
    return 0


async def _run(args: argparse.Namespace) -> int:
    from langchain_core.messages import HumanMessage

    from open_deep_research import tracing
    from open_deep_research.guard import BudgetExceeded

    approver = auto_approve if getattr(args, "auto_approve", False) else interactive_approve
    async with open_checkpointer() as saver:
        graph = _compile(saver)
        if args.command == "sessions":
            rows = await list_threads(saver, args.limit)
            if not rows:
                print("No saved runs yet.")
                return 0
            for row in rows:
                snap = await graph.aget_state({"configurable": {"thread_id": row["thread"]}})
                values = snap.values or {}
                msgs = values.get("messages") or []
                question = str(getattr(msgs[0], "content", "")) if msgs else ""
                waiting = bool(snap.tasks and any(t.interrupts for t in snap.tasks))
                state = "done" if values.get("final_report") and not snap.next else "waiting for approval" if waiting else "in progress"
                print(f"{row['thread']}  {row['updated'][:19]}  {state:20}  {question[:70]}")
            return 0
        if args.command == "ask":
            from open_deep_research.configuration import Configuration
            from open_deep_research.followup import answer, model_asker, render

            snap = await graph.aget_state({"configurable": {"thread_id": args.thread}})
            if not snap.values:
                print(f"No checkpoint for thread {args.thread}")
                return 1
            cfg = Configuration.from_runnable_config({"configurable": {}})
            model = args.model or cfg.final_report_model
            try:
                result = await answer(args.question, snap.values, model_asker(model, cfg.final_report_model_max_tokens))
            except ValueError as exc:
                print(str(exc))
                return 1
            text = render(result)
            if args.out:
                with open(args.out, "a", encoding="utf-8") as fh:
                    fh.write(text + "\n")
                print(f"Follow-up appended to {args.out}")
            else:
                print(text)
            return 0 if not result["flagged_urls"] else 2
        if args.command == "status":
            snap = await graph.aget_state({"configurable": {"thread_id": args.thread}})
            if not snap.values:
                print(f"No checkpoint for thread {args.thread}")
                return 1
            waiting = bool(snap.tasks and any(t.interrupts for t in snap.tasks))
            print(f"thread: {args.thread}\nnext: {list(snap.next) or 'done'}\nwaiting for approval: {waiting}\nreport ready: {bool(snap.values.get('final_report'))}")
            return 0
        thread = args.thread or uuid.uuid4().hex[:12]
        first = None if args.command == "resume" else {"messages": [HumanMessage(content=args.question)]}
        print(f"thread: {thread}  (resume with: crossvet resume --thread {thread})", file=sys.stderr)
        callbacks = tracing.get_callbacks()
        budget = set_run_limits(getattr(args, "effort", None), getattr(args, "max_usd", None), getattr(args, "question", ""))
        callbacks = [*callbacks, *budget]
        result: dict[str, Any] = {}
        try:
            try:
                result = await drive(graph, first, thread, approver, callbacks)
            except BudgetExceeded as exc:
                print(f"crossvet: {exc}", file=sys.stderr)
            finally:
                for guard in budget:
                    print(guard.summary(), file=sys.stderr)
            if any(guard.tripped for guard in budget):
                print(f"The run stopped at the spend cap; anything written below may be partial. To go further: "
                      f"crossvet resume --thread {thread} --max-usd <higher>", file=sys.stderr)
                if result.get("final_report"):
                    _write_report(result, args.out)
                return 3
            if tracing.score_run(result, callbacks):
                print("Langfuse: review scores attached to this run's trace.", file=sys.stderr)
        finally:
            tracing.flush()
        _write_report(result, args.out)
        return 0


def _version() -> str:
    from importlib.metadata import PackageNotFoundError, version

    try:
        return version("crossvet")
    except PackageNotFoundError:
        return "unknown"


def build_parser() -> argparse.ArgumentParser:
    """CLI argument parser."""
    p = argparse.ArgumentParser(prog="crossvet", description="Deep research with cross-vendor review and durable checkpoints.",
                                epilog=START_HERE, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--version", action="version", version=f"crossvet {_version()}")
    sub = p.add_subparsers(dest="command", required=True)
    run = sub.add_parser("run", aliases=["research"], help="start a new research run")
    run.add_argument("question")
    run.add_argument("--thread", help="thread id (default: random)")
    run.add_argument("--estimate", action="store_true", help="print a rough cost range for this run and stop (no model is called)")
    resume = sub.add_parser("resume", help="continue a run from its last checkpoint")
    resume.add_argument("--thread", required=True)
    for sp in (run, resume):
        sp.add_argument("--effort", choices=effort_choices(), help=EFFORT_HELP)
        sp.add_argument("--max-usd", type=float, help="stop before the next model call once this much is spent (default: MAX_RUN_USD; 0 = no cap)")
        sp.add_argument("--auto-approve", action="store_true", help="approve any pause without asking")
        sp.add_argument("--out", help="write the final report to this file")
    status = sub.add_parser("status", help="show where a run stopped")
    status.add_argument("--thread", required=True)
    ask = sub.add_parser("ask", help="ask a follow-up question about a finished run, answered from its research notes")
    ask.add_argument("--thread", required=True)
    ask.add_argument("question")
    ask.add_argument("--model", help="model for the answer (default: FINAL_REPORT_MODEL)")
    ask.add_argument("--out", help="append the answer to this markdown file")
    review = sub.add_parser("review", help="review an existing report against its sources (files or URLs)")
    review.add_argument("report", help="the report to review (Markdown or text file)")
    review.add_argument("--sources", nargs="+", required=True, help="files (Markdown, text, HTML) or http(s) URLs the report should rest on")
    review.add_argument("--brief", default="", help="the question the report answers (helps reviewers judge coverage)")
    review.add_argument("--panel", help="comma-separated review models (default: REVIEW_MODELS)")
    review.add_argument("--out", help="write the reviewed report to this file (default: print it)")
    sessions = sub.add_parser("sessions", help="list saved runs, newest first")
    sessions.add_argument("--limit", type=int, default=20)
    return p


async def _review(args: argparse.Namespace) -> int:
    from open_deep_research.review_doc import areview

    report = Path(args.report).read_text(encoding="utf-8")
    config = {"review_models": args.panel} if args.panel else {}
    try:
        result = await areview(report, args.sources, args.brief, config)
    except (ValueError, RuntimeError, OSError) as exc:
        print(f"crossvet review: {exc}", file=sys.stderr)
        return 1
    review = result.get("review", {})
    disputed = len((review.get("critic") or {}).get("disputed") or [])
    print(f"review: {review.get('status')}; scores {review.get('scores')}; citations not in sources: "
          f"{len(review.get('flagged_urls') or [])}; flagged sources: {len(review.get('injected_sources') or [])}; disputed: {disputed}",
          file=sys.stderr)
    if args.out:
        Path(args.out).write_text(result["final_report"], encoding="utf-8")
        print(f"Reviewed report written to {args.out}", file=sys.stderr)
    else:
        print(result["final_report"])
    return 0


EFFORT_HELP = ("how much work the run does: quick, standard or deep (default: EFFORT, else standard); "
               "auto picks from the question, in code. Your own settings always win over the tier")


def effort_choices() -> tuple[str, ...]:
    """Tier names accepted by ``--effort``."""
    from open_deep_research.effort import CHOICES

    return CHOICES


def set_run_limits(effort: str | None, max_usd: float | None, question: str = "") -> list[Any]:
    """Apply ``--effort`` and ``--max-usd`` to this process; return the spend-cap callbacks for the run."""
    from open_deep_research.configuration import Configuration
    from open_deep_research.effort import classify
    from open_deep_research.guard import budget_callbacks

    tier = effort or os.environ.get("EFFORT", "")
    if tier == "auto":
        tier, reason = classify(question) if question else ("standard", "there is no question to read when resuming")
        print(f"effort: {tier} (chosen because {reason})", file=sys.stderr)
    if tier:
        os.environ["EFFORT"] = tier
    if max_usd is not None:
        os.environ["MAX_RUN_USD"] = str(max_usd)
    return budget_callbacks(Configuration.from_runnable_config({"configurable": {}}).max_run_usd)


# Tools that have their own command (``crossvet-scan`` and so on) are also subcommands of ``crossvet``.
# name: (module, one-line help, the equivalent standalone command)
TOOLS: dict[str, tuple[str, str, str]] = {
    "demo": ("demo", "see what Crossvet does in under a minute: no keys, no network, no cost", "crossvet-demo"),
    "scan": ("scan_cli", "check pages for prompt injection (no model, no key)", "crossvet-scan"),
    "try": ("quickrun", "one research run that saves the report, the review and a shareable summary", "crossvet-try"),
    "setup": ("setup_wizard", "write .env: find the models your keys can call and pick a review panel", "crossvet-setup"),
    "doctor": ("doctor", "check the configuration without spending tokens", "crossvet-doctor"),
    "bench": ("bench", "measure which model to use for each role", "crossvet-bench"),
    "compare": ("compare", "run the same questions under several setups and compare", "crossvet-compare"),
    "dataset": ("dataset", "build an evaluation dataset from finished runs", "crossvet-dataset"),
    "mcp": ("mcp_server", "start the MCP server for Claude Code, Codex or Cursor", "crossvet-mcp"),
    "chat": ("chat.cli", "one chat that routes each request to a suitable model (`crossvet chat --help`)", "crossvet-chat"),
}
START_TOOLS = ("demo", "scan", "setup", "doctor", "chat")
START_HERE = """start here:
  crossvet demo                                  a one-minute tour: no keys, no network, no cost
  crossvet scan URL_OR_FILE                      check a page for hidden instructions aimed at AI (free, no keys)
  crossvet setup                                 one-time: write .env in this folder from the API keys you have
  crossvet doctor                                check that setup without spending anything
  crossvet research "QUESTION" --estimate        see the cost range first, then drop --estimate to run it
  crossvet review REPORT --sources FILE_OR_URL   have several vendors' models review a report you already have
  crossvet chat                                  one chat that routes each request to a suitable model

more tools (each takes --help):
""" + "\n".join(f"  crossvet {name:8} {help_}" for name, (_, help_, _) in TOOLS.items() if name not in START_TOOLS)

# Commands that run on the light install (no research extra).
LIGHT = ("demo", "scan", "chat")
RESEARCH_MISSING = """crossvet {command} needs the research extra, which this install does not have.
Install it with:  uv tool install --force "crossvet[research] @ git+https://github.com/j-zulick/crossvet"
(or, in a virtual environment:  pip install "crossvet[research] @ git+https://github.com/j-zulick/crossvet").
The chat, the scanner and the demo work without it."""


def research_installed() -> bool:
    """Whether the research pipeline's dependencies can be imported."""
    import importlib.util

    return all(importlib.util.find_spec(name) is not None for name in ("langgraph", "langchain_core", "pydantic"))


def _tool(name: str, rest: list[str]) -> int:
    """Run one of the standalone tools with ``rest`` as its arguments."""
    import importlib
    import inspect

    module, _, prog = TOOLS[name]
    tool_main = importlib.import_module(f"open_deep_research.{module}").main
    if inspect.signature(tool_main).parameters:
        return int(tool_main(rest) or 0)
    saved = sys.argv
    sys.argv = [prog, *rest]  # these tools read sys.argv themselves
    try:
        return int(tool_main() or 0)
    finally:
        sys.argv = saved


def main(argv: list[str] | None = None) -> int:
    """Entry point."""
    argv = list(sys.argv[1:] if argv is None else argv)
    load_env()  # before any tool, so every command reads the same .env
    if not argv:
        build_parser().print_help()
        return 0
    if argv[0] not in LIGHT and not argv[0].startswith("-") and not research_installed():
        print(RESEARCH_MISSING.format(command=argv[0]), file=sys.stderr)
        return 2
    if argv and argv[0] in TOOLS:
        return _tool(argv[0], argv[1:])
    args = build_parser().parse_args(argv)
    if args.command == "review":
        return asyncio.run(_review(args))
    if getattr(args, "estimate", False):
        return _estimate(args)
    return asyncio.run(_run(args))


if __name__ == "__main__":
    raise SystemExit(main())
