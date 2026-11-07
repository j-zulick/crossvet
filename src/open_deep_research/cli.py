"""Command-line runner with durable checkpoints.

Every step of a run is checkpointed, so a crashed or interrupted run resumes where it
stopped instead of starting over (and paying for completed model calls again).

    crossvet run "question" [--thread ID] [--auto-approve] [--out report.md]
    crossvet resume --thread ID [--auto-approve] [--out report.md]
    crossvet status --thread ID

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
from typing import Any, AsyncIterator, Callable

from dotenv import load_dotenv
from langchain_core.messages import HumanMessage
from langgraph.types import Command

from open_deep_research import tracing

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
        payload = Command(resume=approver(interrupts[0].value))
    raise RuntimeError(f"More than {max_pauses} pauses in one run; stopping.")


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


async def _run(args: argparse.Namespace) -> int:
    approver = auto_approve if getattr(args, "auto_approve", False) else interactive_approve
    async with open_checkpointer() as saver:
        graph = _compile(saver)
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
        try:
            result = await drive(graph, first, thread, approver, tracing.get_callbacks())
        finally:
            tracing.flush()
        _write_report(result, args.out)
        return 0


def build_parser() -> argparse.ArgumentParser:
    """CLI argument parser."""
    p = argparse.ArgumentParser(prog="crossvet", description="Deep research with cross-vendor review and durable checkpoints.")
    sub = p.add_subparsers(dest="command", required=True)
    run = sub.add_parser("run", help="start a new research run")
    run.add_argument("question")
    run.add_argument("--thread", help="thread id (default: random)")
    resume = sub.add_parser("resume", help="continue a run from its last checkpoint")
    resume.add_argument("--thread", required=True)
    for sp in (run, resume):
        sp.add_argument("--auto-approve", action="store_true", help="approve any pause without asking")
        sp.add_argument("--out", help="write the final report to this file")
    status = sub.add_parser("status", help="show where a run stopped")
    status.add_argument("--thread", required=True)
    return p


def main(argv: list[str] | None = None) -> int:
    """Entry point."""
    load_dotenv()
    args = build_parser().parse_args(argv)
    return asyncio.run(_run(args))


if __name__ == "__main__":
    raise SystemExit(main())
