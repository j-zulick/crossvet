"""Re-run the review stage of a pilot run from its checkpoint, with Jev support checks off, on, or on with REVIEW_SUPPORT_CLAIM=fact.

    PILOT_CHECKPOINTS=<pilot out>/checkpoints.sqlite uv run python docs/evals/2026-11-18-jev/jev_ab.py <question 0-2> <off|on|fact> [tag]
"""
import asyncio, json, os, sys, time
from pathlib import Path
from dotenv import load_dotenv

qi, mode = int(sys.argv[1]), sys.argv[2]
tag = sys.argv[3] if len(sys.argv) > 3 else ""
load_dotenv()  # run from the repository root, with your .env
os.environ.update({
    "CROSS_VENDOR_REVIEW_ENABLED": "true",
    "REVIEW_MODELS": "openai:gpt-5.4-mini,anthropic:claude-sonnet-5-5",
    "FINAL_REPORT_MODEL": "openai:gpt-5.4-mini",
    "REVIEW_DELIBERATION_ROUNDS": "2",
    "REVIEW_BLIND_PASS_ENABLED": "true",
    "REVIEW_SUPPORT_CHECKER": "jev" if mode in ("on", "fact") else "",
    "REVIEW_SUPPORT_CLAIM": "fact" if mode == "fact" else "finding",
    "RUN_EXPORT_PATH": f"jev-out/export-q{qi}-{mode}{tag}.jsonl",
    # Checkpoints of the Nov 17 pilot runs (docs/evals/2026-11-17-pilot/sliced_run.py), stopped before review.
    "CROSSVET_CHECKPOINTS": os.environ.get("PILOT_CHECKPOINTS", "pilot-out/checkpoints.sqlite"),
})
from open_deep_research import compare, cross_vendor_review as rc
from open_deep_research.cli import _compile, open_checkpointer

async def main():
    async with open_checkpointer() as saver:
        graph = _compile(saver)
        cfg = {"configurable": {"thread_id": f"review-q{qi}"}}
        state = None
        async for snap in graph.aget_state_history(cfg):
            if snap.next == ("cross_vendor_review",):
                state = snap.values
                break
    assert state, "no pre-review checkpoint"
    from langchain_core.callbacks import get_usage_metadata_callback
    t = time.perf_counter()
    with get_usage_metadata_callback() as cb:
        out = await asyncio.wait_for(rc.cross_vendor_review(state, {"configurable": {}}), 172)
    usage = {m: {"input": u.get("input_tokens", 0), "output": u.get("output_tokens", 0)} for m, u in cb.usage_metadata.items()}
    rev = out.get("review", {})
    keep = {k: rev.get(k) for k in ("status", "scores", "flagged_urls", "critic", "deliberation", "blind_pass", "support_check")}
    rec = {"question": qi, "jev": mode, "seconds": round(time.perf_counter() - t, 1), "usage": usage, "review": keep,
           "final_report": out.get("final_report", "")}
    Path(f"jev-out/q{qi}-{mode}{tag}.json").write_text(json.dumps(rec, indent=1, default=str))
    print("ok", rec["seconds"], json.dumps(keep.get("support_check"))[:300])

asyncio.run(main())
