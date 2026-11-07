"""Tests for the setup comparison harness (offline)."""

import asyncio
import json
import os

import pytest

from open_deep_research import compare
from open_deep_research.compare import RunResult, Setup

from .test_end_to_end import SOURCE_URL, scripted  # noqa: F401  (pytest fixture)


def test_load_setups_validates(tmp_path):
    good = tmp_path / "s.toml"
    good.write_text('[[setup]]\nname = "a"\n[setup.config]\nreview_models = "openai:x,anthropic:y"\n')
    assert compare.load_setups(good) == [Setup("a", {"review_models": "openai:x,anthropic:y"})]

    unknown = tmp_path / "u.toml"
    unknown.write_text('[[setup]]\nname = "a"\n[setup.config]\nnot_a_setting = 1\n')
    with pytest.raises(ValueError, match="unknown settings: not_a_setting"):
        compare.load_setups(unknown)

    dup = tmp_path / "d.toml"
    dup.write_text('[[setup]]\nname = "a"\n[[setup]]\nname = "a"\n')
    with pytest.raises(ValueError, match="duplicate"):
        compare.load_setups(dup)

    bad_name = tmp_path / "n.toml"
    bad_name.write_text('[[setup]]\nname = "../x"\n')
    with pytest.raises(ValueError, match="needs a name"):
        compare.load_setups(bad_name)


def test_load_questions_skips_comments(tmp_path):
    q = tmp_path / "q.txt"
    q.write_text("# heading\n\nFirst question?\n  Second question?  \n")
    assert compare.load_questions(q) == ["First question?", "Second question?"]


def test_applied_sets_and_restores_env(monkeypatch):
    monkeypatch.setenv("REVIEW_MODELS", "original")
    monkeypatch.delenv("CROSS_VENDOR_REVIEW_ENABLED", raising=False)
    with compare.applied(Setup("a", {"review_models": ["openai:x", "anthropic:y"], "cross_vendor_review_enabled": True})):
        assert os.environ["REVIEW_MODELS"] == "openai:x,anthropic:y"
        assert os.environ["CROSS_VENDOR_REVIEW_ENABLED"] == "true"
        assert os.environ["REQUIRE_APPROVAL"] == "false"
    assert os.environ["REVIEW_MODELS"] == "original"
    assert "CROSS_VENDOR_REVIEW_ENABLED" not in os.environ


def test_score_reads_review_state():
    out = {
        "final_report": "See https://a.org/x and https://b.org/y. Again https://a.org/x.",
        "review": {"status": "ok", "flagged_urls": ["https://b.org/y"], "failed": ["x:y"], "scores": {"m1": 6, "m2": 8},
                   "critic": {"status": "ok", "dropped": 2, "disputed": [{"id": "C1-U1"}]}},
    }
    r = compare.score(RunResult("s", "q", 1), out)
    assert (r.cited_urls, r.flagged_urls, r.failed_reviewers) == (2, 1, 1)
    assert r.mean_reviewer_score == 7
    assert (r.critic_dropped, r.critic_disputed, r.review_status) == (2, 1, "ok")


def test_summary_rates_and_errors(tmp_path):
    results = [
        RunResult("a", "q1", 1, cited_urls=4, flagged_urls=1, seconds=10, mean_reviewer_score=6),
        RunResult("a", "q2", 1, cited_urls=4, flagged_urls=0, seconds=20, mean_reviewer_score=8),
        RunResult("b", "q1", 1, status="error", error="boom"),
    ]
    rows = compare.write_outputs(results, tmp_path)
    a, b = rows
    assert a["flagged_url_rate"] == 0.125 and a["mean_seconds"] == 15 and a["mean_reviewer_score"] == 7
    assert b["finished"] == 0 and b["flagged_url_rate"] is None
    assert len((tmp_path / "results.jsonl").read_text().splitlines()) == 3
    assert "| b | 1 | 0 | —" in (tmp_path / "summary.md").read_text()


def test_failed_run_is_recorded_not_raised(tmp_path):
    async def boom(question, callbacks):
        raise RuntimeError("provider down")

    r = asyncio.run(compare.run_one(Setup("a", {}), "q", 1, tmp_path, runner=boom))
    assert r.status == "error" and "provider down" in r.error


def test_compare_runs_real_graph_per_setup(scripted, monkeypatch, tmp_path):  # noqa: F811
    """Two setups through the real research graph with scripted models."""
    monkeypatch.delenv("CROSS_VENDOR_REVIEW_ENABLED", raising=False)
    setups = [
        Setup("no-review", {"cross_vendor_review_enabled": False}),
        Setup("review", {"cross_vendor_review_enabled": True, "review_models": "openai:a,anthropic:b", "review_reviser_model": "google_genai:c"}),
    ]
    results = asyncio.run(compare.compare(setups, ["How much solar capacity was added in 2025?"], 1, tmp_path))
    by = {r.setup: r for r in results}
    assert all(r.status == "ok" for r in results), [r.error for r in results]
    assert by["no-review"].review_status == "off"
    assert by["review"].review_status == "ok" and by["review"].mean_reviewer_score == 7
    assert by["review"].cited_urls >= 1 and by["review"].flagged_urls == 0
    assert "CROSS_VENDOR_REVIEW_ENABLED" not in os.environ  # restored after each run
    lines = [json.loads(x) for x in (tmp_path / "results.jsonl").read_text().splitlines()]
    assert [x["setup"] for x in lines] == ["no-review", "review"]
    assert SOURCE_URL in open(by["review"].report_path).read()


def test_usage_counter_sums_tokens_per_model():
    from uuid import uuid4

    from langchain_core.messages import AIMessage
    from langchain_core.outputs import ChatGeneration, LLMResult

    counter = compare.UsageCounter()
    for model, (i, o) in [("gpt-x", (100, 20)), ("gpt-x", (50, 5)), ("claude-y", (10, 1))]:
        rid = uuid4()
        asyncio.run(counter.on_chat_model_start({}, [], run_id=rid, invocation_params={"model": model}))
        msg = AIMessage(content="", usage_metadata={"input_tokens": i, "output_tokens": o, "total_tokens": i + o})
        asyncio.run(counter.on_llm_end(LLMResult(generations=[[ChatGeneration(message=msg)]]), run_id=rid))
    assert counter.usage == {"gpt-x": {"input": 150, "output": 25}, "claude-y": {"input": 10, "output": 1}}


def test_langfuse_traces_are_tagged_and_scored(monkeypatch, tmp_path):
    from open_deep_research import tracing

    class FakeHandler:
        last_trace_id = "trace-123"

    class FakeClient:
        def __init__(self):
            self.scores = []

        def create_score(self, **kw):
            self.scores.append(kw)

    client = FakeClient()
    monkeypatch.setattr(tracing, "get_callbacks", lambda: [FakeHandler()])
    monkeypatch.setattr(tracing, "flush", lambda: None)
    monkeypatch.setattr(compare, "langfuse_client", lambda: client)
    seen = {}

    async def runner(question, callbacks):
        seen["metadata"] = compare.RUN_METADATA.get()
        seen["handlers"] = callbacks
        return {"final_report": "See https://a.org and https://b.org", "review": {"status": "ok", "flagged_urls": ["https://b.org"], "scores": {"m": 8}}}

    results = asyncio.run(compare.compare([Setup("panel", {})], ["Q?"], 1, tmp_path, runner=runner))
    meta = seen["metadata"]
    assert meta["langfuse_session_id"].startswith("crossvet-compare-") and "setup:panel" in meta["langfuse_tags"]
    assert any(isinstance(h, FakeHandler) for h in seen["handlers"])
    assert results[0].langfuse_trace_id == "trace-123"
    by_name = {s["name"]: s["value"] for s in client.scores}
    assert by_name["finished"] == 1 and by_name["cited_urls"] == 2 and by_name["flagged_url_rate"] == 0.5 and by_name["reviewer_score"] == 8
    assert all(s["trace_id"] == "trace-123" for s in client.scores)
    assert compare.RUN_METADATA.get() == {}


def test_no_langfuse_means_no_metadata(monkeypatch, tmp_path):
    from open_deep_research import tracing

    monkeypatch.setattr(tracing, "get_callbacks", lambda: [])
    seen = {}

    async def runner(question, callbacks):
        seen["metadata"] = compare.RUN_METADATA.get()
        return {"final_report": ""}

    r = asyncio.run(compare.run_one(Setup("a", {}), "q", 1, tmp_path, runner=runner))
    assert seen["metadata"] == {} and r.langfuse_trace_id == ""
