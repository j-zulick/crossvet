"""Compare model setups on the same research questions.

Runs every question against every setup (any mix of hosted, OpenRouter, Ollama or
local models in any role) and records what each run produced:

- whether it finished, how long it took, and input/output tokens per model
- how many URLs the report cites and how many the citation check flagged
- reviewer scores, critic outcomes (findings dropped or disputed), failed reviewers
- with deliberation on: position changes backed by the notes, and ungrounded ones;
  rounds run and saved by early stopping, why deliberation stopped, and how many
  findings the challengers endorsed
- with the blind pass on: grounded points the draft omitted
- with a support checker (Jev): passages scored and rejected as not supporting their claim

    crossvet-compare --setups setups.toml --questions questions.txt [--repeats 2] [--out compare-results]

``setups.toml`` lists named setups; each ``config`` table uses Crossvet's
configuration field names (the lowercase form of the environment variables)::

    [[setup]]
    name = "hosted"
    [setup.config]
    research_model = "openai:gpt-6.1-sol"
    review_models = "openai:gpt-5.4-mini,anthropic:claude-sonnet-5-5"

    [[setup]]
    name = "local"
    [setup.config]
    research_model = "ollama:qwen3:32b"
    review_models = "local:model-a,local:model-b"

Add ``edition = "deep_agent"`` next to a setup's name to run the Deep Agents edition
instead of the LangGraph edition.

``questions.txt`` has one question per line; blank lines and lines starting with ``#``
are ignored. Results go to ``results.jsonl`` (one line per run), ``summary.csv`` and
``summary.md`` (one row per setup), plus every report under ``reports/``.

Setups run one at a time, because each run applies its setup through environment
variables (which take precedence over other configuration). Runs never pause for
approval.
"""

from __future__ import annotations

import argparse
import asyncio
import contextvars
import csv
import hashlib
import json
import os
import re
import statistics
import sys
import time
import tomllib
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Awaitable, Callable, Iterator
from uuid import UUID

from langchain_core.callbacks import AsyncCallbackHandler
from langchain_core.messages import HumanMessage

URL_RE = re.compile(r"https?://[^\s)\]>\"']+")
EDITIONS = ("langgraph", "deep_agent")
FORCED = {"REQUIRE_APPROVAL": "false", "ALLOW_CLARIFICATION": "false"}


@dataclass
class Setup:
    """A named set of configuration overrides."""

    name: str
    config: dict[str, Any]
    edition: str = "langgraph"


@dataclass
class RunResult:
    """Everything recorded about one run."""

    setup: str
    question: str
    repeat: int
    status: str = "ok"
    error: str = ""
    seconds: float = 0.0
    input_tokens: int = 0
    output_tokens: int = 0
    tokens_by_model: dict[str, dict[str, int]] = field(default_factory=dict)
    report_chars: int = 0
    cited_urls: int = 0
    flagged_urls: int = 0
    review_status: str = "off"
    mean_reviewer_score: float | None = None
    failed_reviewers: int = 0
    critic_dropped: int = 0
    critic_disputed: int = 0
    position_changes: int = 0
    unsupported_changes: int = 0
    deliberation_rounds: int = 0
    rounds_saved: int = 0
    stop_reason: str = ""
    agreement_rate: float | None = None
    deliberation_calls: int = 0
    blind_omissions: int = 0
    support_checked: int = 0
    support_rejected: int = 0
    report_path: str = ""
    langfuse_trace_id: str = ""


def config_fields() -> set[str]:
    """Return the configuration field names a setup may set."""
    from open_deep_research.configuration import Configuration

    return set(Configuration.model_fields)


def load_setups(path: str | Path) -> list[Setup]:
    """Read and validate setups from a TOML file."""
    data = tomllib.loads(Path(path).read_text(encoding="utf-8"))
    raw = data.get("setup") or []
    if not raw:
        raise ValueError(f"{path}: no [[setup]] entries")
    allowed = config_fields()
    setups: list[Setup] = []
    seen: set[str] = set()
    for i, entry in enumerate(raw, 1):
        name = str(entry.get("name") or "").strip()
        if not name or not re.fullmatch(r"[A-Za-z0-9_.-]+", name):
            raise ValueError(f"{path}: setup {i} needs a name made of letters, digits, '.', '_' or '-'")
        if name in seen:
            raise ValueError(f"{path}: duplicate setup name '{name}'")
        seen.add(name)
        config = dict(entry.get("config") or {})
        unknown = sorted(set(config) - allowed)
        if unknown:
            raise ValueError(f"{path}: setup '{name}' has unknown settings: {', '.join(unknown)}")
        edition = str(entry.get("edition") or "langgraph")
        if edition not in EDITIONS:
            raise ValueError(f"{path}: setup '{name}' has unknown edition '{edition}' (use {' or '.join(EDITIONS)})")
        setups.append(Setup(name, config, edition))
    return setups


def load_questions(path: str | Path) -> list[str]:
    """Read questions, one per line."""
    lines = Path(path).read_text(encoding="utf-8").splitlines()
    questions = [ln.strip() for ln in lines if ln.strip() and not ln.strip().startswith("#")]
    if not questions:
        raise ValueError(f"{path}: no questions")
    return questions


def _env_value(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (list, tuple)):
        return ",".join(str(v) for v in value)
    if isinstance(value, dict):
        return json.dumps(value)
    return str(value)


@contextmanager
def applied(setup: Setup) -> Iterator[None]:
    """Apply a setup through environment variables, restoring them afterwards."""
    overrides = {k.upper(): _env_value(v) for k, v in setup.config.items()} | FORCED
    saved = {k: os.environ.get(k) for k in overrides}
    os.environ.update(overrides)
    try:
        yield
    finally:
        for key, old in saved.items():
            if old is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = old


class UsageCounter(AsyncCallbackHandler):
    """Counts input/output tokens per model from LangChain usage metadata."""

    def __init__(self) -> None:  # noqa: D107
        self.models: dict[UUID, str] = {}
        self.usage: dict[str, dict[str, int]] = {}

    async def on_chat_model_start(self, serialized: dict[str, Any], messages: Any, *, run_id: UUID, **kwargs: Any) -> None:  # noqa: D102
        params = kwargs.get("invocation_params") or {}
        meta = kwargs.get("metadata") or {}
        name = params.get("model") or params.get("model_name") or meta.get("ls_model_name") or params.get("_type") or "unknown"
        self.models[run_id] = str(name)

    async def on_llm_end(self, response: Any, *, run_id: UUID, **kwargs: Any) -> None:  # noqa: D102
        name = self.models.pop(run_id, "unknown")
        for gens in getattr(response, "generations", []) or []:
            for gen in gens:
                usage = getattr(getattr(gen, "message", None), "usage_metadata", None) or {}
                slot = self.usage.setdefault(name, {"input": 0, "output": 0})
                slot["input"] += int(usage.get("input_tokens", 0) or 0)
                slot["output"] += int(usage.get("output_tokens", 0) or 0)


def score(result: RunResult, out: dict[str, Any]) -> RunResult:
    """Fill report and review metrics from a finished run's output state."""
    report = out.get("final_report") or ""
    result.report_chars = len(report)
    result.cited_urls = len({u.rstrip(".,;") for u in URL_RE.findall(report)})
    review = out.get("review") or {}
    result.review_status = review.get("status", "off") if review else "off"
    result.flagged_urls = len(review.get("flagged_urls") or [])
    result.failed_reviewers = len(review.get("failed") or [])
    scores = [s for s in (review.get("scores") or {}).values() if isinstance(s, (int, float))]
    result.mean_reviewer_score = round(statistics.mean(scores), 2) if scores else None
    critic = review.get("critic") or {}
    dropped = critic.get("dropped", 0)
    result.critic_dropped = dropped if isinstance(dropped, int) else len(dropped or [])
    result.critic_disputed = len(critic.get("disputed") or [])
    deliberation = review.get("deliberation") or {}
    result.position_changes = int(deliberation.get("changed_with_evidence", 0))
    result.unsupported_changes = int(deliberation.get("unsupported_changes", 0))
    result.deliberation_rounds = int(deliberation.get("rounds_run", 0) or 0)
    result.rounds_saved = int(deliberation.get("rounds_saved", 0) or 0)
    result.stop_reason = str(deliberation.get("stop_reason") or "")
    rate = deliberation.get("agreement_rate")
    result.agreement_rate = float(rate) if isinstance(rate, (int, float)) else None
    result.deliberation_calls = int(deliberation.get("model_calls", 0) or 0)
    result.blind_omissions = int((review.get("blind_pass") or {}).get("omitted", 0) or 0)
    result.support_checked = int(deliberation.get("support_checked", 0) or 0)
    result.support_rejected = int(deliberation.get("support_rejected", 0) or 0) + int((review.get("blind_pass") or {}).get("unsupported", 0) or 0)
    return result


Runner = Callable[[str, list[Any]], Awaitable[dict[str, Any]]]


RUN_METADATA: contextvars.ContextVar[dict[str, Any]] = contextvars.ContextVar("crossvet_run_metadata", default={})


async def default_runner(question: str, callbacks: list[Any], edition: str = "langgraph") -> dict[str, Any]:
    """Run one edition's graph once without a checkpointer."""
    if edition == "deep_agent":
        from open_deep_research.deep_agent import deep_agent as graph
    else:
        from open_deep_research.deep_researcher import deep_researcher as graph

    config = {"callbacks": callbacks, "recursion_limit": 200, "metadata": RUN_METADATA.get()}
    return await graph.ainvoke({"messages": [HumanMessage(content=question)]}, config)


# ---------------------------------------------------------------------------
# Langfuse: every run becomes a trace, grouped by comparison, tagged by setup and scored
# ---------------------------------------------------------------------------
LANGFUSE_SCORES = {
    "cited_urls": "cited_urls",
    "flagged_urls": "flagged_urls",
    "mean_reviewer_score": "reviewer_score",
    "critic_dropped": "critic_dropped",
    "critic_disputed": "critic_disputed",
    "seconds": "seconds",
    "deliberation_rounds": "deliberation_rounds",
    "rounds_saved": "rounds_saved",
    "agreement_rate": "agreement_rate",
    "deliberation_calls": "deliberation_calls",
    "blind_omissions": "blind_omissions",
    "support_checked": "support_checked",
    "support_rejected": "support_rejected",
}


def langfuse_metadata(session_id: str, setup: Setup, question: str, repeat: int) -> dict[str, Any]:
    """Trace metadata Langfuse reads: one session per comparison, tags per setup."""
    return {
        "langfuse_session_id": session_id,
        "langfuse_tags": ["crossvet-compare", f"setup:{setup.name}", f"edition:{getattr(setup, 'edition', 'langgraph')}"],
        "crossvet_setup": setup.name,
        "crossvet_question": question,
        "crossvet_repeat": repeat,
    }


def push_scores(result: RunResult, client: Any) -> None:
    """Attach the run's metrics to its Langfuse trace (best effort, never raises)."""
    if not result.langfuse_trace_id or client is None:
        return
    try:
        client.create_score(name="finished", value=1 if result.status == "ok" else 0, trace_id=result.langfuse_trace_id, data_type="BOOLEAN")
        for attr, name in LANGFUSE_SCORES.items():
            value = getattr(result, attr)
            if isinstance(value, (int, float)):
                client.create_score(name=name, value=float(value), trace_id=result.langfuse_trace_id, data_type="NUMERIC")
        if result.stop_reason:
            client.create_score(name="stop_reason", value=result.stop_reason, trace_id=result.langfuse_trace_id, data_type="CATEGORICAL")
        if result.cited_urls:
            client.create_score(name="flagged_url_rate", value=round(result.flagged_urls / result.cited_urls, 4),
                                trace_id=result.langfuse_trace_id, data_type="NUMERIC")
    except Exception:
        pass  # tracing must never break a comparison


def langfuse_client() -> Any:
    """Return the Langfuse client when tracing is configured, else None."""
    from open_deep_research import tracing

    if not tracing.langfuse_enabled():
        return None
    try:
        from langfuse import get_client

        return get_client()
    except Exception:
        return None


async def run_one(setup: Setup, question: str, repeat: int, reports_dir: Path, runner: Runner = default_runner, session_id: str = "") -> RunResult:
    """Run one question under one setup and record the result."""
    from open_deep_research import tracing

    result = RunResult(setup=setup.name, question=question, repeat=repeat)
    counter = UsageCounter()
    tracers = tracing.get_callbacks()
    token = RUN_METADATA.set(langfuse_metadata(session_id, setup, question, repeat) if tracers else {})
    start = time.perf_counter()
    try:
        with applied(setup):
            handlers = [counter, *tracers]
            out = await (default_runner(question, handlers, setup.edition) if runner is default_runner else runner(question, handlers))
        score(result, out)
        path = reports_dir / setup.name / f"{hashlib.sha1(question.encode()).hexdigest()[:10]}-r{repeat}.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(out.get("final_report") or "", encoding="utf-8")
        result.report_path = str(path)
    except Exception as exc:  # one failed run must not stop the comparison
        result.status = "error"
        result.error = f"{type(exc).__name__}: {str(exc)[:300]}"
    finally:
        RUN_METADATA.reset(token)
    result.seconds = round(time.perf_counter() - start, 2)
    result.langfuse_trace_id = next((t for t in (getattr(h, "last_trace_id", None) for h in tracers) if t), "")
    result.tokens_by_model = counter.usage
    result.input_tokens = sum(v["input"] for v in counter.usage.values())
    result.output_tokens = sum(v["output"] for v in counter.usage.values())
    return result


def _mean(values: list[float]) -> float | None:
    return round(statistics.mean(values), 2) if values else None


def summarize(results: list[RunResult]) -> list[dict[str, Any]]:
    """One row per setup, averaging over finished runs."""
    rows = []
    for name in dict.fromkeys(r.setup for r in results):
        runs = [r for r in results if r.setup == name]
        ok = [r for r in runs if r.status == "ok"]
        cited = sum(r.cited_urls for r in ok)
        rows.append({
            "setup": name,
            "runs": len(runs),
            "finished": len(ok),
            "mean_seconds": _mean([r.seconds for r in ok]),
            "mean_input_tokens": _mean([r.input_tokens for r in ok]),
            "mean_output_tokens": _mean([r.output_tokens for r in ok]),
            "cited_urls": cited,
            "flagged_url_rate": round(sum(r.flagged_urls for r in ok) / cited, 3) if cited else None,
            "mean_reviewer_score": _mean([r.mean_reviewer_score for r in ok if r.mean_reviewer_score is not None]),
            "critic_dropped": sum(r.critic_dropped for r in ok),
            "critic_disputed": sum(r.critic_disputed for r in ok),
            "failed_reviewers": sum(r.failed_reviewers for r in ok),
            "grounded_position_changes": sum(r.position_changes for r in ok),
            "ungrounded_position_changes": sum(r.unsupported_changes for r in ok),
            "mean_deliberation_rounds": _mean([r.deliberation_rounds for r in ok if r.deliberation_rounds]),
            "rounds_saved": sum(r.rounds_saved for r in ok),
            "mean_agreement_rate": _mean([r.agreement_rate for r in ok if r.agreement_rate is not None]),
            "deliberation_calls": sum(r.deliberation_calls for r in ok),
            "blind_omissions": sum(r.blind_omissions for r in ok),
            "support_checked": sum(r.support_checked for r in ok),
            "support_rejected": sum(r.support_rejected for r in ok),
        })
    return rows


def write_outputs(results: list[RunResult], out_dir: Path) -> list[dict[str, Any]]:
    """Write results.jsonl, summary.csv and summary.md; return the summary rows."""
    out_dir.mkdir(parents=True, exist_ok=True)
    with open(out_dir / "results.jsonl", "w", encoding="utf-8") as fh:
        for r in results:
            fh.write(json.dumps(asdict(r), ensure_ascii=False) + "\n")
    rows = summarize(results)
    with open(out_dir / "summary.csv", "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    cols = list(rows[0])
    lines = ["| " + " | ".join(cols) + " |", "|" + "---|" * len(cols)]
    lines += ["| " + " | ".join("—" if row[c] is None else str(row[c]) for c in cols) + " |" for row in rows]
    note = (
        "\n\n`flagged_url_rate` is the share of cited URLs that research never read. Reviewer scores come from "
        "each setup's own panel, so compare them across setups only when the panels match. Read the reports "
        "under `reports/` before drawing conclusions."
    )
    (out_dir / "summary.md").write_text("# Crossvet setup comparison\n\n" + "\n".join(lines) + note + "\n", encoding="utf-8")
    return rows


async def compare(setups: list[Setup], questions: list[str], repeats: int, out_dir: Path, runner: Runner = default_runner) -> list[RunResult]:
    """Run every question under every setup, ``repeats`` times each."""
    results = []
    total = len(setups) * len(questions) * repeats
    n = 0
    session_id = f"crossvet-compare-{time.strftime('%Y%m%d-%H%M%S')}"
    client = langfuse_client()
    for setup in setups:
        for question in questions:
            for rep in range(1, repeats + 1):
                n += 1
                print(f"[{n}/{total}] {setup.name}: {question[:70]}", file=sys.stderr)
                result = await run_one(setup, question, rep, out_dir / "reports", runner, session_id)
                push_scores(result, client)
                results.append(result)
    write_outputs(results, out_dir)
    if client is not None:
        from open_deep_research import tracing

        tracing.flush()
        print(f"Langfuse: traces in session {session_id} (filter by tag setup:<name>)", file=sys.stderr)
    return results


def main(argv: list[str] | None = None) -> int:
    """Command-line entry point."""
    from dotenv import load_dotenv

    p = argparse.ArgumentParser(prog="crossvet-compare", description="Compare model setups on the same research questions.")
    p.add_argument("--setups", required=True, help="TOML file with [[setup]] entries")
    p.add_argument("--questions", required=True, help="text file, one question per line")
    p.add_argument("--repeats", type=int, default=1, help="runs per question and setup (default 1)")
    p.add_argument("--out", default="compare-results", help="output directory (default compare-results)")
    args = p.parse_args(argv)
    if args.repeats < 1:
        p.error("--repeats must be at least 1")
    load_dotenv()
    try:
        setups, questions = load_setups(args.setups), load_questions(args.questions)
    except (OSError, ValueError, tomllib.TOMLDecodeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    results = asyncio.run(compare(setups, questions, args.repeats, Path(args.out)))
    print((Path(args.out) / "summary.md").read_text(encoding="utf-8"))
    return 0 if any(r.status == "ok" for r in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
