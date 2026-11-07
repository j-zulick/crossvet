"""Unit tests for the research-gateway search adapter (no network)."""

import asyncio
import json

from open_deep_research import gateway_search as gs
from open_deep_research.gateway_search import _tool_args, parse_gateway_response


def test_parses_nested_read_results():
    payload = {
        "status": "partial",
        "sources": [
            {"rank": 1, "url": "https://a.example", "title": "A", "engine": "brave",
             "read": {"status": "ok", "final_url": "https://a.example/final", "markdown": "Body A"}},
            {"rank": 2, "url": "https://b.example", "snippet": "snip B", "read": {"status": "blocked"}},
            {"title": "no url"},
        ],
    }
    out = parse_gateway_response(json.dumps(payload))
    assert [s.url for s in out] == ["https://a.example/final", "https://b.example"]
    assert out[0].content == "Body A" and out[0].engine == "brave" and out[0].extra["rank"] == 1
    assert out[1].status == "blocked" and out[1].snippet == "snip B"


def test_parses_text_content_blocks_and_alternate_keys():
    blocks = [{"type": "text", "text": json.dumps({"results": [{"url": "https://c.example", "content": "C"}]})}]
    out = parse_gateway_response(blocks)
    assert out[0].url == "https://c.example" and out[0].content == "C"


def test_unparseable_text_returns_no_sources():
    assert parse_gateway_response("not json") == []


class FakeTool:
    name = "search_and_read"

    def __init__(self, args, responses):
        self.args, self.responses, self.calls = args, responses, []

    async def ainvoke(self, args):
        self.calls.append(args)
        r = self.responses[args["query"]]
        if isinstance(r, Exception):
            raise r
        return r


def test_tool_args_follow_advertised_schema():
    assert _tool_args(FakeTool({"query": {}, "max_sources": {}}, {}), "q", 3) == {"query": "q", "max_sources": 3}
    assert _tool_args(FakeTool({"query": {}}, {}), "q", 3) == {"query": "q"}


def test_one_failing_query_does_not_sink_batch(monkeypatch):
    tool = FakeTool({"query": {}}, {
        "good": json.dumps({"sources": [{"url": "https://ok.example", "content": "x"}]}),
        "bad": RuntimeError("boom"),
    })

    async def fake_load():
        return tool

    monkeypatch.setattr(gs, "load_gateway_tool", fake_load)
    results = dict(asyncio.run(gs.gateway_search_raw(["good", "bad"])))
    assert results["good"][0].url == "https://ok.example"
    assert results["bad"][0].status == "error:RuntimeError"


def test_missing_settings_raise_clear_error(monkeypatch):
    monkeypatch.delenv("RESEARCH_GATEWAY_URL", raising=False)
    monkeypatch.delenv("RESEARCH_GATEWAY_TOKEN", raising=False)
    try:
        asyncio.run(gs.load_gateway_tool())
    except RuntimeError as e:
        assert "RESEARCH_GATEWAY_URL" in str(e)
    else:
        raise AssertionError("expected RuntimeError")


def test_contract_matches_gateway_search_and_read_shape():
    """Fixture mirrors the gateway's searchAndRead() reply: per-source rank/url/title/engine/snippet plus a read result."""
    payload = {
        "status": "partial",
        "search_status": "ok",
        "elapsed_ms": 4210,
        "sources": [
            {"rank": 1, "url": "https://a.example/p", "title": "A", "engine": "brave", "snippet": "about A",
             "read": {"status": "ok", "extractor": "firecrawl", "url": "https://a.example/p", "final_url": None, "title": None,
                      "http_status": 200, "markdown": "Body A", "retrieved_at": "2026-11-07T00:00:00Z", "truncated": False,
                      "total_chars": 6, "returned_chars": 6, "escalation_reason": "native_thin"}},
            {"rank": 2, "url": "https://b.example", "title": None, "engine": None, "snippet": None,
             "read": {"status": "failed", "url": "https://b.example", "outcome": "all_extractors_failed"}},
            {"rank": 3, "url": "https://c.example", "engine": "mojeek", "status": "skipped_time_budget"},
        ],
    }
    out = parse_gateway_response([{"type": "text", "text": json.dumps(payload)}])
    assert [s.url for s in out] == ["https://a.example/p", "https://b.example", "https://c.example"]
    a, b, c = out
    assert a.title == "A" and a.content == "Body A" and a.engine == "brave" and a.status == "ok"
    assert a.extra == {"rank": 1, "extractor": "firecrawl", "truncated": False, "retrieved_at": "2026-11-07T00:00:00Z", "escalation_reason": "native_thin"}
    assert b.status == "failed" and b.content == "" and b.extra["outcome"] == "all_extractors_failed" and b.engine is None
    assert c.status == "skipped_time_budget"


def test_tool_args_use_num_read_when_advertised():
    assert _tool_args(FakeTool({"query": {}, "num_read": {}, "render": {}}, {}), "q", 4) == {"query": "q", "num_read": 4}
