"""Tests for the human approval step, using a real LangGraph interrupt (no models)."""

import asyncio
import operator
from typing import Annotated

import pytest
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command
from typing_extensions import TypedDict

from open_deep_research.approval import (
    ACTION_NAME,
    approve_research,
    build_approval_request,
    count_sources,
    parse_decision,
)


class S(TypedDict, total=False):
    messages: Annotated[list, operator.add]
    notes: list[str]
    raw_notes: list[str]
    research_brief: str
    final_report: str


async def fake_report(state: S):
    extra = [m.content for m in state.get("messages", []) if "Additional instructions" in getattr(m, "content", "")]
    return {"final_report": "REPORT" + (f" [{extra[-1]}]" if extra else "")}


def _graph():
    b = StateGraph(S)
    b.add_node("approve_research", approve_research)
    b.add_node("final_report_generation", fake_report)
    b.add_edge(START, "approve_research")
    b.add_edge("final_report_generation", END)
    return b.compile(checkpointer=InMemorySaver())


STATE = {"research_brief": "Brief", "notes": ["see https://a.example/x"], "raw_notes": ["https://a.example/x and https://b.example"], "messages": []}


def _run(graph, thread, payload):
    return asyncio.run(graph.ainvoke(payload, {"configurable": {"thread_id": thread}}))


def test_request_matches_agent_chat_ui_schema():
    req = build_approval_request(STATE)
    action = req["action_requests"][0]
    assert action["name"] == ACTION_NAME and isinstance(action["args"], dict)
    assert action["args"]["sources_found"] == 2
    assert req["review_configs"][0] == {"action_name": ACTION_NAME, "allowed_decisions": ["approve", "edit", "reject"]}


def test_count_sources_dedupes_trailing_punctuation():
    assert count_sources(["https://a.example/x.", "https://a.example/x/", "https://b.example"]) == 2


@pytest.mark.parametrize(
    "resume, expected",
    [
        ({"decisions": [{"type": "approve"}]}, ("approve", "", "")),
        ({"decisions": [{"type": "edit", "edited_action": {"name": ACTION_NAME, "args": {"instructions": " focus on cost "}}}]}, ("approve", "focus on cost", "")),
        ({"decisions": [{"type": "reject", "message": "wrong scope"}]}, ("reject", "", "wrong scope")),
        (True, ("approve", "", "")),
        (False, ("reject", "", "Rejected by reviewer.")),
        ("shorter please", ("approve", "shorter please", "")),
        ({"decisions": []}, ("reject", "", "Unrecognized approval response; nothing was written.")),
        (42, ("reject", "", "Unrecognized approval response; nothing was written.")),
    ],
)
def test_parse_decision(resume, expected):
    assert parse_decision(resume) == expected


def test_disabled_passes_straight_through(monkeypatch):
    monkeypatch.delenv("REQUIRE_APPROVAL", raising=False)
    out = _run(_graph(), "t0", STATE)
    assert out["final_report"] == "REPORT"


def test_pauses_then_approves_with_instructions(monkeypatch):
    monkeypatch.setenv("REQUIRE_APPROVAL", "true")
    g = _graph()
    first = _run(g, "t1", STATE)
    assert "final_report" not in first
    intr = first["__interrupt__"][0].value
    assert intr["action_requests"][0]["name"] == ACTION_NAME
    edit = {"decisions": [{"type": "edit", "edited_action": {"name": ACTION_NAME, "args": {"instructions": "for executives"}}}]}
    out = _run(g, "t1", Command(resume=edit))
    assert out["final_report"] == "REPORT [Additional instructions for the final report: for executives]"


def test_reject_stops_without_writing(monkeypatch):
    monkeypatch.setenv("REQUIRE_APPROVAL", "true")
    g = _graph()
    _run(g, "t2", STATE)
    out = _run(g, "t2", Command(resume={"decisions": [{"type": "reject", "message": "off topic"}]}))
    assert out["final_report"] == "Report not written: off topic"
