"""End-to-end run of the real research graph with scripted models (no network, no keys).

A single scripted chat model plays every role: clarifier, brief writer, supervisor,
researcher, summarizer, compressor, report writer and reviewers. Web search is
replaced by canned results. This exercises the real node wiring, tool loops,
routing and the cross-vendor review on every release branch.
"""

import asyncio
from typing import Any

import pytest
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.runnables import RunnableLambda

from open_deep_research import cross_vendor_review, deep_researcher, utils

SOURCE_URL = "https://example.org/solar-capacity-2025"
REPORT = (
    "# Solar capacity in 2025\n\nGlobal solar additions grew strongly in 2025 [1].\n\n"
    f"### Sources\n[1] Solar capacity report: {SOURCE_URL}\n"
)


def _tool_name(tool: Any) -> str:
    if isinstance(tool, dict):
        return tool.get("name") or tool.get("type", "")
    return getattr(tool, "name", None) or getattr(tool, "__name__", "")


def _structured(schema: type) -> Any:
    name = schema.__name__
    if name == "ClarifyWithUser":
        return schema(need_clarification=False, question="", verification="Starting research now.")
    if name == "ResearchQuestion":
        return schema(research_brief="How much solar capacity was added worldwide in 2025?")
    if name == "Summary":
        return schema(summary="Solar additions grew strongly in 2025.", key_excerpts="grew strongly in 2025")
    if name == "Critique":
        return schema(unsupported_claims=["'grew strongly' is not quantified"], suggested_revisions=["Add the figure"], overall_score=7)
    if name == "Ballot":
        return schema(ranking=["C1", "C2"], confidence=0.8)
    if name == "CriticReport":
        return schema(verdicts=[])
    if name == "ChallengeSet":
        return schema(challenges=[{"finding_id": "C1-U1", "objection": "The notes say it grew strongly.", "evidence_quote": "Solar additions grew strongly in 2025."}])
    if name == "ResponseSet":
        return schema(responses=[{"finding_id": "C1-U1", "stance": "WITHDRAW", "evidence_quote": "Solar additions grew strongly in 2025."}])
    raise AssertionError(f"unexpected structured output request: {name}")


class ScriptedModel(BaseChatModel):
    """Chat model that answers according to the role implied by its bound tools."""

    tool_names: list[str] = []
    bound: dict = {}
    calls: list[str] = []

    @property
    def _llm_type(self) -> str:
        return "scripted"

    def bind_tools(self, tools: Any, **kwargs: Any) -> "ScriptedModel":  # noqa: D102
        if kwargs:
            self.bound.update(kwargs)
        return self.model_copy(update={"tool_names": [_tool_name(t) for t in tools]})

    def with_structured_output(self, schema: Any, **kwargs: Any) -> Any:  # noqa: D102
        def respond(_input: Any) -> Any:
            self.calls.append(f"structured:{schema.__name__}")
            return _structured(schema)

        return RunnableLambda(respond)

    def _generate(self, messages, stop=None, run_manager=None, **kwargs) -> ChatResult:
        tools_seen = sum(isinstance(m, ToolMessage) for m in messages)
        if "ConductResearch" in self.tool_names:  # supervisor
            self.calls.append("supervisor")
            if tools_seen == 0:
                call = {"name": "ConductResearch", "args": {"research_topic": "Global solar additions in 2025"}, "id": "sup-1"}
            else:
                call = {"name": "ResearchComplete", "args": {}, "id": "sup-2"}
            msg = AIMessage(content="", tool_calls=[call])
        elif "tavily_search" in self.tool_names:  # researcher
            self.calls.append("researcher")
            if tools_seen == 0:
                msg = AIMessage(content="", tool_calls=[{"name": "tavily_search", "args": {"queries": ["solar capacity 2025"]}, "id": "res-1"}])
            else:
                msg = AIMessage(content="I have enough information.")
        elif "web_search" in self.tool_names:  # researcher with OpenAI's built-in search
            self.calls.append("researcher-native")
            if not any(isinstance(m, AIMessage) for m in messages):
                msg = AIMessage(content=[
                    {"type": "web_search_call", "id": "ws_1", "status": "completed",
                     "action": {"type": "search", "query": "solar 2025", "sources": [{"type": "url", "url": SOURCE_URL + "?utm_source=openai"}]}},
                    {"type": "text", "text": "Solar additions grew strongly in 2025.",
                     "annotations": [{"type": "url_citation", "url": SOURCE_URL + "?utm_source=openai", "title": "Solar capacity report"}]},
                ])
            else:
                msg = AIMessage(content="I have enough information.")
        else:  # compression, final report, revision
            self.calls.append("text")
            msg = AIMessage(content=REPORT)
        return ChatResult(generations=[ChatGeneration(message=msg)])


@pytest.fixture
def scripted(monkeypatch):
    model = ScriptedModel(calls=[])

    async def fake_search(queries, **kwargs):
        return [
            {
                "query": q,
                "results": [{"url": SOURCE_URL, "title": "Solar capacity report", "content": "Solar additions grew strongly in 2025.", "raw_content": "Solar additions grew strongly in 2025. " * 20}],
            }
            for q in queries
        ]

    monkeypatch.setattr(deep_researcher, "configurable_model", model)
    monkeypatch.setattr(utils, "tavily_search_async", fake_search)
    monkeypatch.setattr(utils, "init_chat_model", lambda **kwargs: model)
    monkeypatch.setattr(cross_vendor_review, "build_reviewer", lambda *args, **kwargs: model)
    for key in ("REQUIRE_APPROVAL", "RUN_EXPORT_PATH", "REVIEW_DELIBERATION_ROUNDS", "REVIEW_DELIBERATION_EARLY_STOP"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("SEARCH_API", "tavily")
    monkeypatch.setenv("MAX_RESEARCHER_ITERATIONS", "2")
    monkeypatch.setenv("MAX_REACT_TOOL_CALLS", "2")
    return model


def _run(graph, question: str) -> dict:
    return asyncio.run(graph.ainvoke({"messages": [HumanMessage(content=question)]}, {"configurable": {}}))


def test_full_pipeline_without_review(scripted, monkeypatch):
    monkeypatch.setenv("CROSS_VENDOR_REVIEW_ENABLED", "false")
    out = _run(deep_researcher.deep_researcher, "How much solar capacity was added in 2025?")
    assert out["final_report"] == REPORT
    assert out["research_brief"].startswith("How much solar")
    assert any(SOURCE_URL in n for n in out.get("raw_notes", []) + out.get("notes", [])) or SOURCE_URL in out["final_report"]
    assert "supervisor" in scripted.calls and "researcher" in scripted.calls
    assert "structured:Summary" in scripted.calls  # search results were summarized
    assert not out.get("review")


def test_full_pipeline_with_cross_vendor_review(scripted, monkeypatch):
    monkeypatch.setenv("CROSS_VENDOR_REVIEW_ENABLED", "true")
    monkeypatch.setenv("REVIEW_MODELS", "openai:a,anthropic:b")
    monkeypatch.setenv("REVIEW_REVISER_MODEL", "google_genai:c")
    out = _run(deep_researcher.deep_researcher, "How much solar capacity was added in 2025?")
    review = out["review"]
    assert review["status"] == "ok"
    assert set(review["reviewers"]) == {"openai:a", "anthropic:b"}
    assert review["flagged_urls"] == []  # the report only cites what research found
    assert review["reviser_shares_vendor_with"] == []
    assert "## Review notes" in out["final_report"]
    assert "structured:Critique" in scripted.calls and "structured:Ballot" in scripted.calls


def test_full_pipeline_with_openai_native_search(scripted, monkeypatch):
    """OpenAI's built-in search: sources reach the notes, so cited URLs are not flagged."""
    monkeypatch.setenv("SEARCH_API", "openai")
    monkeypatch.setenv("RESEARCH_MODEL", "openai:gpt-5.5")
    monkeypatch.setenv("CROSS_VENDOR_REVIEW_ENABLED", "true")
    monkeypatch.setenv("REVIEW_MODELS", "openai:a,anthropic:b")
    scripted.bound.clear()
    out = _run(deep_researcher.deep_researcher, "How much solar capacity was added in 2025?")
    assert "researcher-native" in scripted.calls
    assert scripted.bound.get("include") == ["web_search_call.action.sources"]
    assert any(SOURCE_URL in n for n in out.get("raw_notes", []))
    assert out["review"]["flagged_urls"] == []


def test_full_pipeline_with_deliberation(scripted, monkeypatch):
    monkeypatch.setenv("CROSS_VENDOR_REVIEW_ENABLED", "true")
    monkeypatch.setenv("REVIEW_MODELS", "openai:a,anthropic:b")
    monkeypatch.setenv("REVIEW_REVISER_MODEL", "google_genai:c")
    monkeypatch.setenv("REVIEW_DELIBERATION_ROUNDS", "2")
    out = _run(deep_researcher.deep_researcher, "How much solar capacity was added in 2025?")
    d = out["review"]["deliberation"]
    assert d["rounds_requested"] == 2 and d["rounds_run"] >= 1
    assert d["changed_with_evidence"] >= 1 and d["unsupported_changes"] == 0
    assert "Deliberation:" in out["final_report"]
    assert "structured:ChallengeSet" in scripted.calls and "structured:ResponseSet" in scripted.calls


def test_stop_policy_is_read_from_configuration(scripted, monkeypatch):
    monkeypatch.setenv("CROSS_VENDOR_REVIEW_ENABLED", "true")
    monkeypatch.setenv("REVIEW_MODELS", "openai:a,anthropic:b")
    monkeypatch.setenv("REVIEW_REVISER_MODEL", "google_genai:c")
    monkeypatch.setenv("REVIEW_DELIBERATION_ROUNDS", "3")
    # The scripted challenger withdraws C1-U1 in round 1 and is silent afterwards.
    monkeypatch.setenv("REVIEW_DELIBERATION_EARLY_STOP", "false")
    legacy = _run(deep_researcher.deep_researcher, "How much solar capacity was added in 2025?")["review"]["deliberation"]
    assert (legacy["rounds_run"], legacy["stop_reason"]) == (2, "no_challenges")
    # With early stopping, silence is not taken as consensus: the guard runs one more round.
    monkeypatch.setenv("REVIEW_DELIBERATION_EARLY_STOP", "true")
    early = _run(deep_researcher.deep_researcher, "How much solar capacity was added in 2025?")["review"]["deliberation"]
    assert early["guard_rounds"] == 1 and early["rounds_run"] == 3 and early["stop_reason"] == "max_rounds"
