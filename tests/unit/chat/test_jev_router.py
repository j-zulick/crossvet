"""Jev as a classifier and an answer check, hosted routers, and choosing the router."""

from __future__ import annotations

import json

import httpx
import pytest

from open_deep_research.chat import cli
from open_deep_research.chat.classify import Task
from open_deep_research.chat.config import parse
from open_deep_research.chat.hub import Hub
from open_deep_research.chat.memory import Memory
from open_deep_research.chat.providers import ProviderError, Reply
from open_deep_research.chat.record import Recorder
from open_deep_research.chat.router import DECISIONS_URL, Jev, JevError, chosen

from .conftest import CONFIG


def decisions(answers: dict, cost: float = 0.00002):
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"], seen["auth"], seen["body"] = str(request.url), request.headers.get("authorization"), json.loads(request.content)
        return httpx.Response(200, json={"model": "typesafe/jev-1.14", "answers": answers, "usage": {"cost": cost}})

    return seen, httpx.MockTransport(handler)


def test_classify_asks_two_choices_and_uses_confident_answers(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key-not-real")
    seen, transport = decisions({"kind": {"type": "choice", "choice": "code", "confidence": 0.9},
                                 "difficulty": {"type": "choice", "choice": "3", "confidence": 0.8}})
    task, cost, note = Jev(transport=transport).classify("make my site faster", Task("general", 2, "rules"))
    assert seen["url"] == DECISIONS_URL and seen["auth"] == "Bearer test-key-not-real"
    assert seen["body"]["model"] == "~typesafe/jev-latest" and seen["body"]["state"] == {"request": "make my site faster"}
    assert {q["type"] for q in seen["body"]["questions"].values()} == {"choice"} and "fresh" in seen["body"]["questions"]["kind"]["criteria"]
    assert (task.kind, task.difficulty, cost) == ("code", 3, 0.00002) and "Jev says code" in note


def test_unsure_jev_leaves_the_rules_in_charge(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key-not-real")
    _, transport = decisions({"kind": {"choice": "writing", "confidence": 0.3}, "difficulty": {"choice": "9", "confidence": 0.9}})
    task, _, note = Jev(transport=transport).classify("x", Task("quick", 1, "rules", True))
    assert (task.kind, task.difficulty, task.wants_json) == ("quick", 1, True) and "unsure" in note


def test_jev_errors_are_jev_errors(monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    with pytest.raises(JevError, match="OPENROUTER_API_KEY"):
        Jev().addresses("q", "a")
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key-not-real")
    failing = httpx.MockTransport(lambda r: httpx.Response(402, json={"error": {"code": 402, "message": "no credit"}}))
    with pytest.raises(JevError, match="HTTP 402"):
        Jev(transport=failing).addresses("q", "a")
    _, empty = decisions({"addresses": {"type": "refusal"}})
    with pytest.raises(JevError, match="no probability"):
        Jev(transport=empty).addresses("q", "a")
    seen, transport = decisions({"addresses": {"type": "noul", "noul": 0.93}})
    assert Jev(transport=transport).addresses("q", "a")[0] == 0.93 and seen["body"]["questions"]["addresses"]["type"] == "noul"


class FakeJev:
    def __init__(self, kind="writing", difficulty=3, addresses=0.9, fail=False):
        self.kind, self.difficulty, self.p, self.fail = kind, difficulty, addresses, fail
        self.calls: list[str] = []

    def classify(self, prompt, fallback, min_confidence=0.5):
        self.calls.append("classify")
        if self.fail:
            raise JevError("HTTP 503 from the Decisions API")
        return Task(self.kind, self.difficulty, f"Jev says {self.kind}", fallback.wants_json), 0.001, ""

    def addresses(self, request, answer):
        self.calls.append("check")
        if self.fail:
            raise JevError("down")
        return self.p, 0.0005


def make(models, jev, **sections) -> Hub:
    return Hub(config=parse({**CONFIG, **sections}, "t"), memory=Memory(":memory:"), caller=models, recorder=Recorder(), jev=jev)


def test_jev_router_classifies_and_its_cost_counts(models):
    jev = FakeJev(kind="writing", difficulty=3)
    hub = make(models, jev, router={"use": "jev"})
    answer = hub.ask("What is the capital of France?")
    assert answer.decision.router == "jev" and answer.decision.task.kind == "writing" and answer.decision.slot == "strong"
    assert answer.cost == pytest.approx(answer.attempts[0].cost + 0.001)
    assert hub.memory.turns(answer.thread)[-1].meta["router"] == "jev"
    # a named model or slot skips Jev
    assert hub.ask("hi", slot="quick").decision.router == "manual" and jev.calls == ["classify"]


def test_jev_failure_falls_back_to_the_rules(models):
    answer = make(models, FakeJev(fail=True), router={"use": "jev"}).ask("What is the capital of France?")
    assert answer.decision.task.kind == "quick" and "Jev failed (HTTP 503" in answer.decision.explain()


def test_hosted_router_goes_first_with_the_rules_slot_as_fallback(models):
    hub = make(models, FakeJev(), router={"use": "openrouter-auto"})
    models.set("openrouter:openrouter/auto", ProviderError("OPENROUTER_API_KEY is not set"))
    answer = hub.ask("Fix this Python bug")
    assert answer.decision.candidates[0] == "openrouter:openrouter/auto" and answer.model == "anthropic:big"
    assert "the 'strong' slot is the fallback" in answer.decision.explain() and answer.escalated
    models.set("openrouter:openrouter/auto", Reply(text="ok", model="", extra={"served_by": "deepseek/v4"}))
    assert hub.ask("Fix this Python bug", router="jev-router").decision.candidates[0] == "openrouter:typesafe/jev-router"


def test_answer_check_moves_on_when_jev_says_the_answer_misses(models):
    jev = FakeJev(addresses=0.05)
    hub = make(models, jev, router={"check": "jev", "check_threshold": 0.2})
    answer = hub.ask("Fix this Python bug")
    assert [a.problem for a in answer.attempts] == ["Jev: does not address the request (p=0.05)"] * 2
    assert answer.model == "anthropic:big"  # every model failed the check: the first answer is kept
    passing = make(models, FakeJev(addresses=0.6), router={"check": "jev"}).ask("Fix this Python bug")
    assert passing.attempts[0].ok and passing.cost == pytest.approx(passing.attempts[0].cost + 0.0005)
    open_fail = make(models, FakeJev(fail=True), router={"check": "jev"}).ask("Fix this Python bug")
    assert open_fail.attempts[0].ok
    quiet = FakeJev()
    make(models, quiet).ask("Fix this Python bug")
    assert quiet.calls == []  # off by default


def test_chosen_router_and_settings(monkeypatch):
    monkeypatch.delenv("CROSSVET_CHAT_ROUTER", raising=False)
    assert chosen("rules") == "rules" and chosen("rules", "jev") == "jev"
    monkeypatch.setenv("CROSSVET_CHAT_ROUTER", "openrouter-auto")
    assert chosen("rules") == "openrouter-auto" and chosen("rules", "jev") == "jev"
    with pytest.raises(ValueError, match="router must be one of"):
        chosen("rules", "magic")
    monkeypatch.setenv("CROSSVET_CHAT_ROUTER", "magic")
    with pytest.raises(ValueError, match="router must be one of"):
        chosen("rules")
    with pytest.raises(ValueError, match=r"\[router\]"):
        parse({"router": {"use": "magic"}})
    cfg = parse({"router": {"use": "jev", "jev_model": "typesafe/jev-1.14", "check": "jev", "check_threshold": 0.3}})
    assert (cfg.router, cfg.jev_model, cfg.check, cfg.check_threshold) == ("jev", "typesafe/jev-1.14", "jev", 0.3)


def test_cli_route_with_a_hosted_router_is_free(models, monkeypatch, capsys):
    monkeypatch.delenv("CROSSVET_CHAT_ROUTER", raising=False)
    monkeypatch.setattr(cli, "load", lambda: parse(CONFIG, "t"))
    assert cli.main(["route", "--json", "--router", "openrouter-auto-code", "Fix this Python bug"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["router"] == "openrouter-auto-code" and data["candidates"][0] == "openrouter:openrouter/auto-code"
    assert models.calls == []


def test_server_router_header(models):
    from starlette.testclient import TestClient

    from open_deep_research.chat.server import create_app

    hub = make(models, FakeJev())
    client = TestClient(create_app(hub, token=""))
    data = client.post("/v1/chat/completions", headers={"x-crossvet-router": "jev"},
                       json={"model": "auto", "messages": [{"role": "user", "content": "What is the capital of France?"}]}).json()
    assert data["crossvet"]["router"] == "jev" and data["crossvet"]["kind"] == "writing"
