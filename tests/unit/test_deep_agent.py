"""Deep Agents edition run end to end with a scripted model (no network, no keys)."""

import asyncio
from typing import Any

import pytest
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.runnables import RunnableLambda

from open_deep_research import cross_vendor_review, deep_agent, utils

from .test_end_to_end import REPORT, SOURCE_URL, _structured, _tool_name

OTHER_URL = "https://example.org/not-in-search-results"


class AgentModel(BaseChatModel):
    """Plays the Deep Agent, its researcher sub-agent and the review panel."""

    tool_names: list[str] = []
    calls: list[str] = []
    report: str = REPORT

    @property
    def _llm_type(self) -> str:
        return "scripted-agent"

    def bind_tools(self, tools: Any, **kwargs: Any) -> "AgentModel":  # noqa: D102
        return self.model_copy(update={"tool_names": [_tool_name(t) for t in tools]})

    def with_structured_output(self, schema: Any, **kwargs: Any) -> Any:  # noqa: D102
        def respond(_input: Any) -> Any:
            self.calls.append(f"structured:{schema.__name__}")
            return _structured(schema)

        return RunnableLambda(respond)

    def _generate(self, messages, stop=None, run_manager=None, **kwargs) -> ChatResult:
        done = {m.name for m in messages if isinstance(m, ToolMessage)}
        if "task" in self.tool_names:  # main agent
            self.calls.append("agent")
            if "task" not in done:
                call = {"name": "task", "args": {"description": "Find 2025 global solar additions", "subagent_type": "researcher"}, "id": "t1"}
            elif "write_file" not in done:
                call = {"name": "write_file", "args": {"file_path": "/report.md", "content": self.report}, "id": "w1"}
            else:
                return ChatResult(generations=[ChatGeneration(message=AIMessage(content="Report written."))])
            return ChatResult(generations=[ChatGeneration(message=AIMessage(content="", tool_calls=[call]))])
        if "web_search" in self.tool_names and "tavily_search" not in self.tool_names:  # sub-agent, built-in search
            self.calls.append("researcher-native")
            msg = AIMessage(content=[
                {"type": "web_search_call", "id": "ws", "status": "completed",
                 "action": {"type": "search", "query": "solar", "sources": [{"type": "url", "url": SOURCE_URL + "?utm_source=openai"}]}},
                {"type": "text", "text": "Solar additions grew strongly in 2025.", "annotations": [{"type": "url_citation", "url": SOURCE_URL, "title": "Solar"}]},
            ])
            return ChatResult(generations=[ChatGeneration(message=msg)])
        if "tavily_search" in self.tool_names:  # researcher sub-agent
            self.calls.append("researcher")
            if "tavily_search" not in done:
                call = {"name": "tavily_search", "args": {"queries": ["solar capacity 2025"]}, "id": "s1"}
                return ChatResult(generations=[ChatGeneration(message=AIMessage(content="", tool_calls=[call]))])
            return ChatResult(generations=[ChatGeneration(message=AIMessage(content=f"Solar additions grew strongly in 2025 ({SOURCE_URL})."))])
        self.calls.append("text")  # summaries, revision
        return ChatResult(generations=[ChatGeneration(message=AIMessage(content=self.report))])


@pytest.fixture
def agent_model(monkeypatch):
    model = AgentModel(calls=[])

    async def fake_search(queries, **kwargs):
        return [{"query": q, "results": [{"url": SOURCE_URL, "title": "Solar capacity report", "content": "Solar additions grew strongly in 2025.", "raw_content": "Solar additions grew strongly in 2025. " * 20}]} for q in queries]

    monkeypatch.setattr(utils, "tavily_search_async", fake_search)
    monkeypatch.setattr(utils, "init_chat_model", lambda **kwargs: model)
    monkeypatch.setattr(deep_agent, "build_reviewer", lambda *a, **k: model)
    monkeypatch.setattr(cross_vendor_review, "build_reviewer", lambda *a, **k: model)
    for key in ("REQUIRE_APPROVAL", "RUN_EXPORT_PATH", "REVIEW_DELIBERATION_ROUNDS", "REVIEW_DELIBERATION_EARLY_STOP"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("SEARCH_API", "tavily")
    monkeypatch.setenv("CROSS_VENDOR_REVIEW_ENABLED", "true")
    monkeypatch.setenv("REVIEW_MODELS", "openai:a,anthropic:b")
    monkeypatch.setenv("REVIEW_REVISER_MODEL", "google_genai:c")
    return model


def _run(question: str) -> dict:
    return asyncio.run(deep_agent.deep_agent.ainvoke({"messages": [HumanMessage(content=question)]}))


def test_deep_agent_edition_researches_writes_and_is_reviewed(agent_model):
    out = _run("How much solar capacity was added in 2025?")
    assert "agent" in agent_model.calls and "researcher" in agent_model.calls
    review = out["review"]
    assert review["status"] == "ok"
    assert review["flagged_urls"] == []  # the sub-agent's search results became the notes
    assert out["final_report"].startswith("# Solar capacity in 2025")
    assert "## Review notes" in out["final_report"]


def test_citation_check_sees_only_real_search_results(agent_model):
    agent_model.report = REPORT + f"[2] Made up: {OTHER_URL}\n"
    out = _run("How much solar capacity was added in 2025?")
    assert out["review"]["flagged_urls"] == [OTHER_URL]


def test_report_from_prefers_file_then_last_message():
    assert deep_agent.report_from({"files": {"/report.md": {"content": "# R"}}, "messages": [AIMessage(content="x")]}) == "# R"
    assert deep_agent.report_from({"files": {"/report.md": {"content": ["# A", "b"]}}}) == "# A\nb"
    assert deep_agent.report_from({"files": {}, "messages": [AIMessage(content="last")]}) == "last"
    assert deep_agent.report_from({}) == ""


def test_draft_comes_from_report_file_without_review(agent_model, monkeypatch):
    monkeypatch.setenv("CROSS_VENDOR_REVIEW_ENABLED", "false")
    agent_model.report = "# Draft from the file\n\nBody [1].\n\n### Sources\n[1] " + SOURCE_URL + "\n"
    out = _run("How much solar capacity was added in 2025?")
    assert out["final_report"] == agent_model.report
    assert not out.get("review")


def test_builtin_search_sources_are_captured(agent_model, monkeypatch):
    monkeypatch.setenv("SEARCH_API", "openai")
    monkeypatch.setenv("RESEARCH_MODEL", "openai:gpt-5.5")
    agent_model.report = REPORT + f"[2] Made up: {OTHER_URL}\n"
    out = _run("How much solar capacity was added in 2025?")
    assert "researcher-native" in agent_model.calls
    assert out["review"]["flagged_urls"] == [OTHER_URL]  # the real source is in the notes; the invented one is not


def test_native_sources_parsing():
    blocks = [
        {"type": "web_search_call", "action": {"sources": [{"url": "https://a.org"}]}},
        {"type": "web_search_tool_result", "content": [{"url": "https://b.org", "title": "B"}]},
        {"type": "text", "text": "fact", "annotations": [{"url": "https://c.org", "title": "C"}]},
        "ignored",
    ]
    text = deep_agent.native_sources(blocks)
    assert "https://a.org" in text and "https://b.org" in text and "https://c.org" in text and "fact" in text
    assert deep_agent.native_sources([{"type": "text", "text": "no sources"}]) == ""
