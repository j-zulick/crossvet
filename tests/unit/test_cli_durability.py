"""Durability tests: a crashed run resumes from its checkpoint without redoing work."""

import asyncio
import operator
from typing import Annotated

import pytest
from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt
from typing_extensions import TypedDict

from open_deep_research import cli, tracing


class S(TypedDict, total=False):
    log: Annotated[list[str], operator.add]
    answer: str


def make_builder(calls: dict, fail_once: dict):
    async def expensive_research(state: S):
        calls["research"] = calls.get("research", 0) + 1
        return {"log": ["researched"]}

    async def flaky_report(state: S):
        calls["report"] = calls.get("report", 0) + 1
        if fail_once.pop("report", False):
            raise ConnectionError("provider dropped the connection")
        return {"answer": "final report", "log": ["reported"]}

    b = StateGraph(S)
    b.add_node("research", expensive_research)
    b.add_node("report", flaky_report)
    b.add_edge(START, "research")
    b.add_edge("research", "report")
    b.add_edge("report", END)
    return b


def test_crash_then_resume_skips_completed_steps_across_processes(tmp_path):
    db = str(tmp_path / "ckpt.sqlite")
    calls: dict = {}
    fail_once = {"report": True}

    async def first_process():
        async with cli.open_checkpointer(db) as saver:
            graph = make_builder(calls, fail_once).compile(checkpointer=saver)
            with pytest.raises(ConnectionError):
                await cli.drive(graph, {"log": []}, "thread-1", cli.auto_approve)

    async def second_process():  # new saver instance = fresh process reading the same file
        async with cli.open_checkpointer(db) as saver:
            graph = make_builder(calls, fail_once).compile(checkpointer=saver)
            return await cli.drive(graph, None, "thread-1", cli.auto_approve)

    asyncio.run(first_process())
    assert calls == {"research": 1, "report": 1}
    result = asyncio.run(second_process())
    assert result["answer"] == "final report"
    assert calls["research"] == 1, "completed (paid) step must not run again"
    assert calls["report"] == 2
    assert result["log"] == ["researched", "reported"]


def test_drive_answers_interrupts_with_approver(tmp_path):
    seen = []

    async def gate(state: S):
        decision = interrupt({"action_requests": [{"name": "write_final_report", "args": {}}], "review_configs": []})
        return {"answer": f"decision={decision['decisions'][0]['type']}"}

    b = StateGraph(S)
    b.add_node("gate", gate)
    b.add_edge(START, "gate")
    b.add_edge("gate", END)

    def approver(request):
        seen.append(request["action_requests"][0]["name"])
        return cli.auto_approve(request)

    async def go():
        async with cli.open_checkpointer(str(tmp_path / "c.sqlite")) as saver:
            return await cli.drive(b.compile(checkpointer=saver), {"log": []}, "t", approver)

    assert asyncio.run(go())["answer"] == "decision=approve"
    assert seen == ["write_final_report"]


def test_interactive_approve_maps_answers(monkeypatch):
    req = {"action_requests": [{"name": "write_final_report", "args": {"research_brief": "b", "sources_found": 3}}]}
    for typed, kind in [("", "approve"), ("r", "reject"), ("focus on pricing", "edit")]:
        monkeypatch.setattr("builtins.input", lambda _prompt, t=typed: t)
        decision = cli.interactive_approve(req)["decisions"][0]
        assert decision["type"] == kind
        if kind == "edit":
            assert decision["edited_action"]["args"]["instructions"] == "focus on pricing"


def test_status_on_unknown_thread_uses_real_graph(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("CROSSVET_CHECKPOINTS", str(tmp_path / "s.sqlite"))
    monkeypatch.delenv("DATABASE_URL", raising=False)
    assert cli.main(["status", "--thread", "nope"]) == 1
    assert "No checkpoint" in capsys.readouterr().out


def test_parser_requires_thread_for_resume():
    with pytest.raises(SystemExit):
        cli.build_parser().parse_args(["resume"])


def test_tracing_off_without_keys(monkeypatch):
    monkeypatch.delenv("LANGFUSE_PUBLIC_KEY", raising=False)
    monkeypatch.delenv("LANGFUSE_SECRET_KEY", raising=False)
    assert tracing.get_callbacks() == []
    tracing.flush()  # no-op, must not raise


def test_tracing_on_with_keys(monkeypatch):
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk-lf-test")
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk-lf-test")
    monkeypatch.setenv("LANGFUSE_BASE_URL", "http://127.0.0.1:9")  # unreachable; nothing is sent in this test
    callbacks = tracing.get_callbacks()
    assert len(callbacks) == 1 and type(callbacks[0]).__name__ == "LangchainCallbackHandler"
