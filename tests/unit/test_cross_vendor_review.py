"""Unit tests for the cross-vendor review (no network, no API keys)."""

import asyncio

import pytest

from open_deep_research import cross_vendor_review as rc
from open_deep_research.cross_vendor_review import (
    Ballot,
    CriticReport,
    CriticVerdict,
    Critique,
    anonymize,
    apply_verdicts,
    check_citations,
    critic_for,
    enumerate_findings,
    parse_review_models,
    quote_in_notes,
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

    critic_report = None  # class-level default: critic agrees with everything

    def with_structured_output(self, schema, **kwargs):
        if self.fail:
            return FakeStructured(RuntimeError("provider down"))
        if schema is Critique:
            return FakeStructured(self.critique)
        if schema is CriticReport:
            return FakeStructured(self.critic_report or CriticReport(verdicts=[]))
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


def test_structured_output_kwargs_per_provider():
    from open_deep_research.utils import structured_output_kwargs

    assert structured_output_kwargs("anthropic:claude-sonnet-5-5") == {"method": "json_schema"}
    assert structured_output_kwargs("openai:gpt-5.5") == {}
    assert structured_output_kwargs("ollama:qwen3:32b") == {}
    assert structured_output_kwargs("") == {}


def test_flatten_native_search_keeps_text_sources_and_tool_calls():
    from langchain_core.messages import AIMessage

    from open_deep_research.utils import flatten_native_search, openai_websearch_called

    msg = AIMessage(content=[
        {"type": "web_search_call", "action": {"query": "jwst launch", "sources": [{"type": "url", "url": "https://science.nasa.gov/webb?utm_source=openai"}]}},
        {"type": "text", "text": "Launched Dec 25, 2021.", "annotations": [{"type": "url_citation", "url": "https://esa.int/webb", "title": "ESA"}]},
        {"type": "function_call", "name": "think_tool", "arguments": "{}"},
    ], tool_calls=[{"name": "think_tool", "args": {"reflection": "ok"}, "id": "c1"}])
    flat = flatten_native_search(msg)
    assert isinstance(flat.content, str)
    assert "Launched Dec 25, 2021." in flat.content and "https://science.nasa.gov/webb" in flat.content and "https://esa.int/webb" in flat.content
    assert "Searched: jwst launch" in flat.content
    assert flat.tool_calls[0]["name"] == "think_tool"
    assert openai_websearch_called(flat)
    assert flatten_native_search(AIMessage(content="plain")).content == "plain"


def test_empty_env_values_fall_back_to_defaults(monkeypatch):
    from open_deep_research.configuration import Configuration

    monkeypatch.setenv("RESEARCH_MODEL", "")
    monkeypatch.setenv("SEARCH_API", "")
    cfg = Configuration.from_runnable_config({"configurable": {}})
    assert cfg.research_model == Configuration.model_fields["research_model"].default
    assert cfg.search_api == Configuration.model_fields["search_api"].default


def test_strip_tracking_removes_only_utm_params():
    text = "See [A](https://a.org/x?utm_source=openai) and https://b.org/y?id=3&utm_medium=x&z=1 and https://c.org/p?utm_source=openai#top."
    out = rc.strip_tracking(text)
    assert "utm_" not in out
    assert "https://a.org/x)" in out and "https://b.org/y?id=3&z=1" in out and "https://c.org/p#top" in out


# ---- Evidence-grounded critic ----

def test_enumerate_findings_ids_are_stable():
    c = Critique(unsupported_claims=["a", "b"], factual_concerns=["c"], overall_score=5)
    assert enumerate_findings(c, "C2") == {"C2-U1": "a", "C2-U2": "b", "C2-F1": "c"}


def test_quote_in_notes_requires_real_meaningful_quote():
    notes = "The study found   a 12% Increase in revenue during 2024."
    assert quote_in_notes("found a 12% increase in revenue", notes)
    assert not quote_in_notes("found a 15% increase in revenue", notes)
    assert not quote_in_notes("12%", notes)  # too short to count as evidence


def test_apply_verdicts_keeps_drops_and_disputes():
    c = Critique(unsupported_claims=["claim A", "claim B", "claim C"], factual_concerns=["concern D"], overall_score=6)
    notes = "Source says revenue grew 12 percent in 2024 according to the filing."
    verdicts = [
        CriticVerdict(finding_id="C1-U1", verdict="AGREE"),
        CriticVerdict(finding_id="C1-U2", verdict="DISAGREE_EVIDENCE", evidence_quote="revenue grew 12 percent in 2024", reason="notes support it"),
        CriticVerdict(finding_id="C1-U3", verdict="DISAGREE_EVIDENCE", evidence_quote="a quote that is not in the notes", reason="made up"),
        CriticVerdict(finding_id="C1-F1", verdict="DISAGREE_CONCERN", reason="speculative"),
    ]
    kept, disputed, dropped = apply_verdicts(c, "C1", verdicts, notes)
    assert kept.unsupported_claims == ["claim A"]
    assert kept.factual_concerns == []
    assert [d["id"] for d in dropped] == ["C1-U2"]
    # an unverifiable "evidence" quote is downgraded to a dispute, never trusted
    assert {d["id"] for d in disputed} == {"C1-U3", "C1-F1"}


def test_findings_without_verdict_are_kept():
    c = Critique(unsupported_claims=["x"], overall_score=5)
    kept, disputed, dropped = apply_verdicts(c, "C1", [], "notes")
    assert kept.unsupported_claims == ["x"] and not disputed and not dropped


def test_critic_is_never_the_author_when_alternatives_exist():
    models = ["openai:a", "anthropic:b", "google_genai:c"]
    for m in models:
        assert critic_for(m, models) != m
    assert critic_for("only:model", ["only:model"]) == "only:model"


def test_node_reports_disputed_and_exports_run(monkeypatch, enabled_env, tmp_path):
    export = tmp_path / "runs" / "review.jsonl"
    monkeypatch.setenv("RUN_EXPORT_PATH", str(export))
    monkeypatch.setenv("REVIEW_MODELS", "openai:a,anthropic:b")
    disputes_everything = CriticReport(verdicts=[
        CriticVerdict(finding_id=f"C{i}-U1", verdict="DISAGREE_CONCERN", reason="not verifiable from notes") for i in (1, 2)
    ])

    def fake_build(model, max_tokens, config):
        m = FakeModel(model, critique=_c(7, f"claim by {model}"))
        m.critic_report = disputes_everything
        return m

    monkeypatch.setattr(rc, "build_reviewer", fake_build)
    out = asyncio.run(rc.cross_vendor_review(_state(), {"configurable": {}}))
    report = out["final_report"]
    assert "### Disputed" in report
    assert "claim by openai:a" in report and "claim by anthropic:b" in report
    assert out["review"]["critic"]["status"] == "ok"
    assert len(out["review"]["critic"]["disputed"]) == 2

    import json
    lines = export.read_text().splitlines()
    assert len(lines) == 1
    rec = json.loads(lines[0])
    assert rec["draft_report"].startswith("Draft cites")
    assert rec["revised_report"].startswith("REVISED REPORT")
    assert len(rec["critic"]["disputed"]) == 2


def test_critic_failure_keeps_findings_and_is_reported(monkeypatch, enabled_env):
    monkeypatch.setenv("REVIEW_MODELS", "openai:a,anthropic:b")

    class CriticDown(FakeModel):
        def with_structured_output(self, schema, **kwargs):
            if schema is CriticReport:
                return FakeStructured(RuntimeError("critic down"))
            return super().with_structured_output(schema)

    monkeypatch.setattr(rc, "build_reviewer", lambda m, t, c: CriticDown(m, critique=_c(7, f"claim by {m}")))
    out = asyncio.run(rc.cross_vendor_review(_state(), {"configurable": {}}))
    assert out["review"]["critic"]["status"].startswith("partial")
    assert "### Disputed" not in out["final_report"]


# ---------------------------------------------------------------------------
# v1.3: fallbacks, timeouts, OpenRouter routing
# ---------------------------------------------------------------------------
def test_failed_reviewer_is_replaced_preferring_a_new_vendor(monkeypatch, enabled_env):
    monkeypatch.setenv("REVIEW_MODELS", "openai:a,anthropic:down")
    monkeypatch.setenv("REVIEW_FALLBACK_MODELS", "openai:spare,openrouter:x-ai/grok")

    def build(model, max_tokens, config):
        return FakeModel(model, fail=model == "anthropic:down", critique=_c(7, model))

    monkeypatch.setattr(rc, "build_reviewer", build)
    out = asyncio.run(rc.cross_vendor_review(_state(), {"configurable": {}}))
    review = out["review"]
    assert review["status"] == "ok" and review["substitutions"] == {"anthropic:down": "openrouter:x-ai/grok"}
    assert set(review["reviewers"]) == {"openai:a", "openrouter:x-ai/grok"}
    assert "Replaced by fallback models: anthropic:down → openrouter:x-ai/grok" in out["final_report"]


def test_slow_reviewer_times_out_and_is_handled_as_a_failure(monkeypatch, enabled_env):
    monkeypatch.setenv("REVIEW_MODELS", "openai:a,anthropic:b,google_genai:slow")
    monkeypatch.setenv("REVIEW_CALL_TIMEOUT", "0.2")

    class Slow(FakeStructured):
        async def ainvoke(self, _messages):
            await asyncio.sleep(5)

    class SlowModel(FakeModel):
        def with_structured_output(self, schema, **kwargs):
            return Slow(None) if schema is Critique else super().with_structured_output(schema, **kwargs)

    monkeypatch.setattr(rc, "build_reviewer", lambda m, t, c: SlowModel(m, critique=_c(7, m)) if m.endswith("slow") else FakeModel(m, critique=_c(7, m)))
    out = asyncio.run(rc.cross_vendor_review(_state(), {"configurable": {}}))
    assert out["review"]["failed"] == ["google_genai:slow"] and out["review"]["status"] == "ok"


def test_openrouter_preferences_from_environment(monkeypatch):
    for k in ("OPENROUTER_PROVIDER_ORDER", "OPENROUTER_ALLOW_FALLBACKS", "OPENROUTER_DATA_COLLECTION"):
        monkeypatch.delenv(k, raising=False)
    assert rc.openrouter_preferences() == {}
    monkeypatch.setenv("OPENROUTER_PROVIDER_ORDER", "together, fireworks")
    monkeypatch.setenv("OPENROUTER_ALLOW_FALLBACKS", "false")
    monkeypatch.setenv("OPENROUTER_DATA_COLLECTION", "deny")
    monkeypatch.setenv("OPENROUTER_API_KEY", "x")
    assert rc.openrouter_preferences() == {"order": ["together", "fireworks"], "allow_fallbacks": False, "data_collection": "deny"}
    llm = rc.build_reviewer("openrouter:z-ai/glm-5", 100, {"configurable": {}})
    assert llm.openrouter_provider == {"order": ["together", "fireworks"], "allow_fallbacks": False, "data_collection": "deny"}
    assert llm.app_title == "Crossvet" and llm.app_url == "https://github.com/j-zulick/crossvet"
    assert rc.vendor_of("openrouter:z-ai/glm-5") == "z-ai"


def test_revision_problem_keeps_the_draft_when_the_revision_is_damaged():
    draft = "Text [1][2][3].\n### Sources\n[1] https://a.example/x\n[2] https://b.example/y\n[3] https://c.example/z\n"
    good = "Better text [1][2][3].\n### Sources\n[1] https://a.example/x\n[2] https://b.example/y\n[3] https://c.example/z\n"
    assert rc.revision_problem(draft, good) == ""
    assert rc.revision_problem(draft, good, truncated=True) == "it stopped at the output limit"
    assert rc.revision_problem(draft, "  ") == "it returned no text"
    assert rc.revision_problem(draft, "Cut off before the sources [1][2") == "it dropped 3 of the draft's 3 sources"
    # Removing a URL the citation check flagged is what the reviser is asked to do.
    assert rc.revision_problem(draft, "T [1].\n[1] https://a.example/x\n", flagged=["https://b.example/y", "https://c.example/z"]) == ""


def test_was_truncated_reads_every_provider_signal():
    from langchain_core.messages import AIMessage

    from open_deep_research.models import was_truncated

    assert was_truncated(AIMessage(content="x", response_metadata={"stop_reason": "max_tokens"}))       # Anthropic
    assert was_truncated(AIMessage(content="x", response_metadata={"finish_reason": "length"}))         # OpenAI chat / OpenRouter
    assert was_truncated(AIMessage(content="x", response_metadata={"incomplete_details": {"reason": "max_output_tokens"}}))  # Responses API
    assert not was_truncated(AIMessage(content="x", response_metadata={"stop_reason": "end_turn"}))


def test_truncated_revision_is_not_used(monkeypatch, enabled_env):
    from langchain_core.messages import AIMessage

    class Truncating(FakeModel):
        async def ainvoke(self, _messages):
            return AIMessage(content="Revised but cut off mid-sent", response_metadata={"stop_reason": "max_tokens"})

    monkeypatch.setattr(rc, "build_reviewer", lambda m, t, c: Truncating(m, critique=_c(6, m)) if m == "anthropic:writer" else FakeModel(m, critique=_c(6, m)))
    monkeypatch.setenv("REVIEW_REVISER_MODEL", "anthropic:writer")
    out = asyncio.run(rc.cross_vendor_review(_state(), {"configurable": {}}))
    assert "cut off mid-sent" not in out["final_report"]
    assert "Revision by anthropic:writer failed (it stopped at the output limit)" in out["final_report"]


def test_review_notes_list_sources_flagged_by_the_injection_check(monkeypatch, enabled_env):
    monkeypatch.setattr(rc, "build_reviewer", lambda m, t, c: FakeModel(m, critique=_c(7, m)))
    state = _state()
    state["raw_notes"] = [
        "--- SOURCE 1: Acme ---\nURL: https://example.com/a\n"
        "INJECTION CHECK: instructions aimed at AI models found (override).\n\nSUMMARY:\nAcme is best.\n"
    ]
    out = asyncio.run(rc.cross_vendor_review(state, {"configurable": {}}))
    assert out["review"]["injected_sources"] == ["https://example.com/a"]
    notes = out["final_report"].split("## Review notes", 1)[1]
    assert "Injection check: 1 source(s)" in notes
    assert "The report cites https://example.com/a" in notes
    disputed = out["final_report"].split("### Disputed", 1)[1]
    assert "REVISED REPORT with https://example.com/a" in disputed and "flagged by the injection check" in disputed
    assert any(d["id"] == "injection" for d in out["review"]["critic"]["disputed"])


def test_review_notes_list_cited_urls_found_only_inside_a_page(monkeypatch, enabled_env):
    """A URL that the notes hold only inside a page's text, never on a URL: line, is listed as unverified."""
    monkeypatch.setattr(rc, "build_reviewer", lambda m, t, c: FakeModel(m, critique=_c(7, m)))
    state = _state()
    state["raw_notes"] = [
        "--- SOURCE 1: Roundup ---\nURL: https://roundup.example/x\n\n"
        "SUMMARY:\nThe page says the primary source is https://example.com/a.\n"
    ]
    out = asyncio.run(rc.cross_vendor_review(state, {"configurable": {}}))
    assert out["review"]["text_only_urls"] == ["https://example.com/a"]
    notes = out["final_report"].split("## Review notes", 1)[1]
    assert "appear only inside another page's text" in notes and "https://example.com/a" in notes
    assert "unverified" in notes


def test_review_notes_skip_the_text_only_check_without_url_lines(monkeypatch, enabled_env):
    monkeypatch.setattr(rc, "build_reviewer", lambda m, t, c: FakeModel(m, critique=_c(7, m)))
    out = asyncio.run(rc.cross_vendor_review(_state(), {"configurable": {}}))  # notes: "Found at https://example.com/a"
    assert out["review"]["text_only_urls"] == []
    assert "only inside another page's text" not in out["final_report"]
