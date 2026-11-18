"""Run one compare job in slices that each fit a short shell call, using LangGraph checkpoints.

    uv run python docs/evals/2026-11-17-pilot/sliced_run.py <setups.toml> <setup-name> <question-index> <outdir> [budget-seconds]

Each call continues the run from its last checkpoint and stops before the budget runs out. Token
usage and time are added up across calls in <outdir>/<setup>-q<i>.state.json. When the run
finishes, the same metrics crossvet-compare records are written to <outdir>/<setup>-q<i>.result.json
and the report to <outdir>/reports/.
"""
import asyncio
import json
import os
import sys
import time
from dataclasses import asdict
from pathlib import Path

from dotenv import load_dotenv
from langchain_core.messages import HumanMessage

from open_deep_research import compare
from open_deep_research.cli import _compile, open_checkpointer


async def main() -> int:
    """Advance one job by one slice; return 0 when it finished, 3 when it needs another call."""
    setups_path, name, qi, outdir = sys.argv[1], sys.argv[2], int(sys.argv[3]), Path(sys.argv[4])
    budget = float(sys.argv[5]) if len(sys.argv) > 5 else 160.0
    load_dotenv()
    setup = next(s for s in compare.load_setups(setups_path) if s.name == name)
    question = [q for q in Path(__file__).with_name("questions.txt").read_text().splitlines() if q.strip()][qi]
    outdir.mkdir(parents=True, exist_ok=True)
    key = f"{name}-q{qi}"
    state_file = outdir / f"{key}.state.json"
    st = json.loads(state_file.read_text()) if state_file.exists() else {"seconds": 0.0, "usage": {}, "calls": 0}
    counter = compare.UsageCounter()
    os.environ["CROSSVET_CHECKPOINTS"] = str(outdir / "checkpoints.sqlite")
    start = time.perf_counter()
    done, out = False, None
    with compare.applied(setup):
        async with open_checkpointer() as saver:
            graph = _compile(saver)
            config = {"configurable": {"thread_id": key}, "callbacks": [counter], "recursion_limit": 200}
            snap = await graph.aget_state(config)
            if snap.values and not snap.next:
                done, out = True, snap.values
            else:
                first = None if snap.values else {"messages": [HumanMessage(content=question)]}
                extra = {"interrupt_before": ["cross_vendor_review"]} if first is not None else {}
                try:
                    out = await asyncio.wait_for(graph.ainvoke(first, config, **extra), timeout=budget)
                    done = not (await graph.aget_state(config)).next
                except TimeoutError:
                    pass
    st["seconds"] += time.perf_counter() - start
    st["calls"] += 1
    for model, u in counter.usage.items():
        slot = st["usage"].setdefault(model, {"input": 0, "output": 0})
        slot["input"] += u["input"]
        slot["output"] += u["output"]
    state_file.write_text(json.dumps(st, indent=1))
    if not done:
        print(f"{key}: continuing (call {st['calls']}, {st['seconds']:.0f}s so far)")  # noqa: T201
        return 3
    result = compare.RunResult(setup=name, question=question, repeat=1)
    compare.score(result, out)
    result.seconds = round(st["seconds"], 2)
    result.tokens_by_model = st["usage"]
    result.input_tokens = sum(v["input"] for v in st["usage"].values())
    result.output_tokens = sum(v["output"] for v in st["usage"].values())
    rep = outdir / "reports" / f"{key}.md"
    rep.parent.mkdir(parents=True, exist_ok=True)
    rep.write_text(out.get("final_report") or "", encoding="utf-8")
    result.report_path = str(rep)
    (outdir / f"{key}.result.json").write_text(json.dumps(asdict(result), indent=1))
    print(f"{key}: finished in {result.seconds:.0f}s over {st['calls']} call(s)")  # noqa: T201
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
