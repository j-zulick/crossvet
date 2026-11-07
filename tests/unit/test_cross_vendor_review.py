"""Unit tests for the cross-vendor review (no network, no API keys)."""

import asyncio

import pytest

from open_deep_research import cross_vendor_review as rc
from open_deep_research.cross_vendor_review import (
    Ballot,
    Critique,
    anonymize,
    check_citations,
    parse_review_models,
    weighted_borda,
)


def _c(score: int, tag: str = "") -> Critique:
    return Critique(unsupported_claims=[tag] if tag else [], overall_score=score)


def test_parse_review_models_strips_and_skips_empty():
    assert parse_review_models(" a:x , ,b:y,") == ["a:x", "b:y"]
    assert parse_review_models("") == []


def test_anonymize_hides_model_names_and_is_bijective():
    crits = {"openai:m": _c(7, "o"), "anthropic:m": _c(8, "a"), "google_genai:m": _c(6, "g")}
    by_label, labels = anonymize(crits, seed=1)
    assert set(by_label) == {"C1", "C2", "C3"}
    assert sorted(labels.values()) == sorted(crits)
    for lbl, model in labels.items():
        assert by_label[lbl] is crits[model]
    # labels carry no vendor information
    assert all(lbl.startswith("C") and lbl[1:].isdigit() for lbl in by_label)


def test_weighted_borda_orders_by_weighted_rank():
    ballots = [
        Ballot(ranking=["C2", "C1", "C3"], confidence=1.0),
        Ballot(ranking=["C2", "C3", "C1"], confidence=0.5),
        Ballot(ranking=["C1", "C2", "C3"], confidence=0.2),
    ]
    tally = weighted_borda(ballots, ["C1", "C2", "C3"])
    assert tally[0][0] == "C2"
    assert [lbl for lbl, _ in tally] == ["C2", "C1", "C3"]


def test_weighted_borda_ignores_unknown_and_duplicate_labels():
    ballots = [Ballot(ranking=["C9", "C1", "C1", "C2"], confidence=1.0)]
    tally = dict(weighted_borda(ballots, ["C1", "C2"]))
    assert tally == {"C1": 2.0, "C2": 1.0}


def test_check_citations_flags_only_unknown_urls():
    notes = "Source: https://example.com/a and https://docs.python.org/3/"
    report = "See [1](https://example.com/a). Also https://docs.python.org/3 and https://made-up.example/x."
    assert check_citations(report, notes) == ["https://made-up.example/x"]


class FakeStructured:
    def __init__(self, result):
        self.result = result

    def with_retry(self, **_):
        return self

    async def ainvoke(self, _messages):
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


class FakeModel:
    """Returns a Critique, Ballot, or revised text depending on what is requested."""

    def __init__(self, name, critique=None, fail=False):
        self.name, self.critique, self.fail = name, critique, fail

    def with_structured_output(self, schema):
        if self.fail:
            return FakeStructured(RuntimeError("provider down"))
        if schema is Critique:
            return FakeStructured(self.critique)
        return FakeStructured(Ballot(ranking=["C1", "C2", "C3"], confidence=0.9))

    async def ainvoke(self, _messages):
        class R:
            content = "REVISED REPORT with https://example.com/a"
        return R()


@pytest.fixture
def enabled_env(monkeypatch):
    monkeypatch.setenv("CROSS_VENDOR_REVIEW_ENABLED", "true")
    monkeypatch.setenv("REVIEW_MODELS", "openai:a,anthropic:b,google_genai:c,openai:broken")


def _state():
    return {
        "final_report": "Draft cites https://example.com/a and https://fake.example/z",
        "raw_notes": ["Found at https://example.com/a"],
        "research_brief": "Test brief",
    }


def test_node_is_noop_when_disabled(monkeypatch):
    monkeypatch.delenv("CROSS_VENDOR_REVIEW_ENABLED", raising=False)
    monkeypatch.delenv("REVIEW_MODELS", raising=False)
    assert asyncio.run(rc.cross_vendor_review(_state(), {"configurable": {}})) == {}


def test_node_runs_with_quorum_and_reports_failures(monkeypatch, enabled_env):
    def fake_build(model, max_tokens, config):
        if model == "openai:broken":
            return FakeModel(model, fail=True)
        return FakeModel(model, critique=_c({"openai:a": 7, "anthropic:b": 8, "google_genai:c": 2}.get(model, 6), model))

    monkeypatch.setattr(rc, "build_reviewer", fake_build)
    out = asyncio.run(rc.cross_vendor_review(_state(), {"configurable": {}}))
    review = out["review"]
    assert review["status"] == "ok"
    assert review["failed"] == ["openai:broken"]
    assert set(review["reviewers"]) == {"openai:a", "anthropic:b", "google_genai:c"}
    assert review["flagged_urls"] == ["https://fake.example/z"]
    assert out["final_report"].startswith("REVISED REPORT")
    assert "## Review notes" in out["final_report"]
    assert "Dissent" in out["final_report"]  # google_genai:c scored far below the mean
    notes_section = out["final_report"].split("## Review notes", 1)[1]
    assert all(line.startswith("- ") for line in notes_section.strip().splitlines())


def test_node_skips_without_quorum(monkeypatch, enabled_env):
    monkeypatch.setattr(rc, "build_reviewer", lambda m, t, c: FakeModel(m, fail=True))
    out = asyncio.run(rc.cross_vendor_review(_state(), {"configurable": {}}))
    assert out["review"]["status"] == "skipped_no_quorum"
    assert "final_report" not in out


def test_build_reviewer_supports_local_and_ollama(monkeypatch):
    monkeypatch.setenv("LOCAL_LLM_BASE_URL", "http://127.0.0.1:1234/v1")
    local = rc.build_reviewer("local:gemma-3-12b", 500, {"configurable": {}})
    assert local.model_name == "gemma-3-12b"
    assert str(local.openai_api_base).startswith("http://127.0.0.1:1234")
    ollama = rc.build_reviewer("ollama:gemma3", 500, {"configurable": {}})
    assert type(ollama).__name__ == "ChatOllama" and ollama.model == "gemma3"


# ---- Reviser independence ----

@pytest.mark.parametrize(
    "model, vendor",
    [
        ("openai:gpt-4.1", "openai"),
        ("anthropic:claude-sonnet-4-5", "anthropic"),
        ("google_genai:gemini-2.5-pro", "google"),
        ("openrouter:anthropic/claude-sonnet-4.5", "anthropic"),
        ("ollama:gemma3", "self-hosted"),
        ("local:qwen", "self-hosted"),
    ],
)
def test_vendor_of(model, vendor):
    assert rc.vendor_of(model) == vendor


def test_reviser_conflicts_detects_same_vendor_across_routes():
    reviewers = ["openrouter:openai/gpt-5", "anthropic:claude-sonnet-4-5"]
    assert rc.reviser_conflicts("openai:gpt-4.1", reviewers) == ["openrouter:openai/gpt-5"]
    assert rc.reviser_conflicts("google_genai:gemini-2.5-pro", reviewers) == []


def test_node_warns_when_reviser_shares_vendor(monkeypatch, enabled_env):
    monkeypatch.setenv("REVIEW_MODELS", "openai:a,anthropic:b")
    monkeypatch.setenv("FINAL_REPORT_MODEL", "openai:writer")
    monkeypatch.setattr(rc, "build_reviewer", lambda m, t, c: FakeModel(m, critique=_c(7)))
    out = asyncio.run(rc.cross_vendor_review(_state(), {"configurable": {}}))
    assert out["review"]["reviser_shares_vendor_with"] == ["openai:a"]
    assert "shares a vendor" in out["final_report"]


def test_independent_reviser_has_no_warning(monkeypatch, enabled_env):
    monkeypatch.setenv("REVIEW_MODELS", "openai:a,anthropic:b")
    monkeypatch.setenv("REVIEW_REVISER_MODEL", "google_genai:writer")
    used = []

    def build(m, t, c):
        used.append(m)
        return FakeModel(m, critique=_c(7))

    monkeypatch.setattr(rc, "build_reviewer", build)
    out = asyncio.run(rc.cross_vendor_review(_state(), {"configurable": {}}))
    assert out["review"]["reviser"] == "google_genai:writer"
    assert out["review"]["reviser_shares_vendor_with"] == []
    assert "shares a vendor" not in out["final_report"]
    assert used[-1] == "google_genai:writer"


def test_failed_revision_keeps_draft_and_says_so(monkeypatch, enabled_env):
    monkeypatch.setenv("REVIEW_MODELS", "openai:a,anthropic:b")
    monkeypatch.setenv("REVIEW_REVISER_MODEL", "google_genai:missing-key")

    def build(m, t, c):
        if m == "google_genai:missing-key":
            raise ValueError("no API key")
        return FakeModel(m, critique=_c(7))

    monkeypatch.setattr(rc, "build_reviewer", build)
    out = asyncio.run(rc.cross_vendor_review(_state(), {"configurable": {}}))
    assert out["final_report"].startswith(_state()["final_report"])
    assert "Revision by google_genai:missing-key failed (ValueError)" in out["final_report"]


def test_citation_check_ignores_tracking_params_scheme_and_www():
    notes = "Source: https://www.example.org/a/?utm_source=openai&id=7 and http://b.org/x#top"
    report = "See https://example.org/a?id=7 and https://b.org/x/ and https://c.org/missing."
    assert rc.check_citations(report, notes) == ["https://c.org/missing"]
    assert rc.check_citations("https://example.org/a?id=8", notes) == ["https://example.org/a?id=8"]


def test_openai_websearch_detected_in_content_blocks():
    from langchain_core.messages import AIMessage

    from open_deep_research.utils import openai_websearch_called

    assert openai_websearch_called(AIMessage(content=[{"type": "web_search_call", "id": "ws"}, {"type": "text", "text": "x"}]))
    assert openai_websearch_called(AIMessage(content="", additional_kwargs={"tool_outputs": [{"type": "web_search_call"}]}))
    assert not openai_websearch_called(AIMessage(content="plain"))
