"""Tool calls pass through, tool loops stay on one model, chat commands, and the crossvet entry point."""

from __future__ import annotations

import json

import httpx
import pytest

from crossvet.chat import cli, providers
from crossvet.chat.config import parse
from crossvet.chat.hub import Hub, in_tool_loop, stronger_slot
from crossvet.chat.memory import Memory
from crossvet.chat.providers import ProviderError, Reply

from .conftest import CONFIG

TOOLS = [{"type": "function", "function": {"name": "read_file", "parameters": {"type": "object", "properties": {}}}}]
CALL = [{"id": "call_1", "type": "function", "function": {"name": "read_file", "arguments": "{}"}}]


class FakeRelay:
    """Scripted pass-through replies per model: a dict message, an Exception, or "" for an empty reply."""

    def __init__(self) -> None:
        self.script: dict[str, object] = {}
        self.calls: list[tuple[str, dict]] = []

    def __call__(self, model: str, body: dict) -> tuple[dict, Reply]:
        self.calls.append((model, body))
        item = self.script.get(model, {"content": f"done by {model}"})
        if isinstance(item, Exception):
            raise item
        message = {"role": "assistant", **item}  # type: ignore[dict-item]
        raw = {"model": model.split(":", 1)[1], "choices": [{"message": message, "finish_reason": "tool_calls" if
               message.get("tool_calls") else "stop"}], "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}}
        reply = Reply(text=message.get("content") or "", model=model, input_tokens=10, output_tokens=5,
                      extra={"tool_calls": message.get("tool_calls") or [], "served_by": raw["model"]})
        return raw, reply


@pytest.fixture
def relay() -> FakeRelay:
    return FakeRelay()


@pytest.fixture
def agent_hub(models, relay) -> Hub:
    return Hub(config=parse(CONFIG, "test"), memory=Memory(":memory:"), caller=models, relayer=relay)


def test_relay_routes_on_the_user_message_and_keeps_tools(agent_hub, relay):
    relay.script["openai:big"] = {"content": None, "tool_calls": CALL}
    body = {"model": "auto", "tools": TOOLS, "temperature": 0.2,
            "messages": [{"role": "system", "content": "agent"}, {"role": "user", "content": "Refactor this Python module"}]}
    raw, answer = agent_hub.relay(body, thread="t1")
    # code goes to strong; the direct Anthropic model is skipped because tools pass through OpenAI-style APIs only
    assert relay.calls[0][0] == "openai:big" and relay.calls[0][1]["tools"] == TOOLS and relay.calls[0][1]["temperature"] == 0.2
    assert answer.tool_calls == CALL and "Direct Anthropic models were skipped" in answer.decision.explain()
    saved = agent_hub.memory.turns("t1")
    assert [t.role for t in saved] == ["user", "assistant"] and saved[1].content == "[tool calls: read_file]"


def test_tool_loop_stays_on_the_model_that_started_it(agent_hub, relay):
    agent_hub.memory.add_turn("t2", "agent", "assistant", "[tool calls: read_file]", model="openai:mid")
    body = {"tools": TOOLS, "messages": [
        {"role": "user", "content": "Refactor this Python module"},
        {"role": "assistant", "content": None, "tool_calls": CALL},
        {"role": "tool", "tool_call_id": "call_1", "content": "file text"}]}
    assert in_tool_loop(body["messages"])
    _, answer = agent_hub.relay(body, thread="t2")
    assert relay.calls[0][0] == "openai:mid" and answer.model == "openai:mid"
    assert "continues a tool loop" in answer.decision.explain()
    # the user's message was already saved when the loop started, so only the answer is added
    assert [t.role for t in agent_hub.memory.turns("t2")] == ["assistant", "assistant"]


def test_relay_escalates_on_error_and_empty_reply(relay, models):
    hub = Hub(config=parse({"slots": {"quick": ["openai:small", "openai:mid"]}}, "t"), memory=Memory(":memory:"),
              caller=models, relayer=relay)
    relay.script["openai:small"] = ProviderError("HTTP 500")
    body = {"tools": TOOLS, "messages": [{"role": "user", "content": "What is 2+2?"}]}
    _, answer = hub.relay(body, thread="t3")
    assert answer.model == "openai:mid" and answer.escalated and answer.attempts[0].problem.startswith("HTTP 500")
    relay.script = {"openai:small": {"content": ""}, "openai:mid": {"content": ""}}
    with pytest.raises(ProviderError, match="every model failed: openai:small: empty answer"):
        hub.relay(body, thread="t4")


def test_relay_refuses_a_slot_with_only_direct_anthropic_models(relay, models):
    cfg = parse({"slots": {"quick": ["anthropic:small"], "balanced": ["anthropic:small"], "strong": ["anthropic:big"]}}, "t")
    hub = Hub(config=cfg, memory=Memory(":memory:"), caller=models, relayer=relay)
    with pytest.raises(RuntimeError, match="OpenAI-style"):
        hub.relay({"tools": TOOLS, "messages": [{"role": "user", "content": "hi"}]}, thread="t")


def test_passthrough_sends_the_whole_request_and_reads_tool_calls(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key-not-real")
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["body"] = json.loads(request.content)
        seen["headers"] = request.headers
        return httpx.Response(200, json={"model": "openai/gpt-x", "choices": [{"message": {"role": "assistant", "content": None,
                              "tool_calls": CALL}, "finish_reason": "tool_calls"}], "usage": {"prompt_tokens": 3, "completion_tokens": 2, "cost": 0.001}})

    body = {"model": "auto", "stream": True, "stream_options": {}, "tools": TOOLS, "messages": [{"role": "user", "content": "x"}]}
    raw, reply = providers.passthrough("openrouter:openrouter/auto", body, httpx.MockTransport(handler))
    assert seen["body"]["model"] == "openrouter/auto" and "stream" not in seen["body"] and seen["body"]["tools"] == TOOLS
    assert seen["headers"]["x-title"] == "Crossvet chat" and seen["body"]["usage"] == {"include": True}
    assert reply.extra["tool_calls"] == CALL and reply.extra["served_by"] == "openai/gpt-x" and reply.cost == 0.001
    with pytest.raises(ProviderError, match="OpenAI-style"):
        providers.passthrough("anthropic:claude-x", body)


def test_served_by_is_recorded_for_hosted_routers(models):
    cfg = parse({"slots": {"balanced": ["openrouter:openrouter/auto"]}}, "t")
    hub = Hub(config=cfg, memory=Memory(":memory:"), caller=models)
    models.set("openrouter:openrouter/auto", Reply(text="hi", model="", extra={"served_by": "google/gemini-x"}))
    answer = hub.ask("Write a short thank-you note")
    assert answer.served_by == "google/gemini-x" and "served by google/gemini-x" in answer.summary()
    assert hub.memory.turns(answer.thread)[-1].meta["served_by"] == "google/gemini-x"


def test_stronger_slot_and_retry(hub, models):
    assert [stronger_slot(s) for s in ("quick", "balanced", "strong", "fresh")] == ["balanced", "strong", "strong", "strong"]
    first = hub.ask("What is the capital of France?", thread="r")
    assert first.decision.slot == "quick"
    again = hub.retry("r", stronger=True)
    assert again.decision.slot == "balanced" and again.model == "openai:mid"
    with pytest.raises(ValueError):
        hub.retry("empty-thread")


@pytest.fixture
def client(agent_hub):
    from starlette.testclient import TestClient

    from crossvet.chat.server import create_app

    return TestClient(create_app(agent_hub, token=""))


def test_server_passes_tools_through_and_streams_tool_calls(client, relay):
    relay.script["openai:big"] = {"content": None, "tool_calls": CALL}
    body = {"model": "auto", "tools": TOOLS, "messages": [{"role": "user", "content": "Debug this Python stack trace"}]}
    data = client.post("/v1/chat/completions", json=body).json()
    message = data["choices"][0]["message"]
    assert message["tool_calls"] == CALL and message["content"] is None and data["choices"][0]["finish_reason"] == "tool_calls"
    assert data["crossvet"]["slot"] == "strong" and data["crossvet"]["turn"] > 0
    streamed = client.post("/v1/chat/completions", json={**body, "stream": True}).text
    first = json.loads(streamed.split("\n\n")[0].removeprefix("data: "))
    assert first["choices"][0]["delta"]["tool_calls"][0]["function"]["name"] == "read_file" and "[DONE]" in streamed


def test_why_and_retry_commands_work_from_any_chat_app(client, models):
    convo = [{"role": "user", "content": "What is the capital of France?"}]
    client.post("/v1/chat/completions", json={"model": "auto", "messages": convo})
    calls = len(models.calls)
    why = client.post("/v1/chat/completions", json={"model": "auto", "messages": convo + [
        {"role": "assistant", "content": "Paris"}, {"role": "user", "content": "/why"}]}).json()
    assert "quick task" in why["choices"][0]["message"]["content"] and len(models.calls) == calls
    retry = client.post("/v1/chat/completions", json={"model": "auto", "messages": convo + [
        {"role": "assistant", "content": "Paris"}, {"role": "user", "content": "/retry stronger"}]}).json()
    assert retry["crossvet"]["slot"] == "balanced" and retry["model"] == "openai:mid"


def test_chat_cli_retry_and_cost(hub, models, monkeypatch, capsys):
    monkeypatch.setattr(cli, "_hub", lambda: hub)
    lines = iter(["What is the capital of France?", "/retry stronger", "/cost", "/quit"])
    monkeypatch.setattr("builtins.input", lambda _: next(lines))
    assert cli.main([]) == 0  # no subcommand starts the chat
    out = capsys.readouterr().out
    assert "openai:mid" in out and "this session: $" in out


def test_crossvet_dispatches_chat(hub, models, monkeypatch, capsys):
    from crossvet import cli as crossvet_cli

    monkeypatch.setattr(cli, "load", lambda: hub.config)
    assert crossvet_cli.main(["chat", "route", "Fix this Python bug"]) == 0
    assert "code task" in capsys.readouterr().out
    assert "crossvet chat" in crossvet_cli.__doc__


def test_every_chat_environment_variable_is_documented():
    import re
    from pathlib import Path

    root = Path(__file__).resolve().parents[3]
    used = set()
    for file in (root / "src" / "crossvet" / "chat").glob("*.py"):
        used |= set(re.findall(r"CROSSVET_CHAT_[A-Z_]+", file.read_text()))
    example = (root / ".env.example").read_text()
    guide = (root / "docs" / "CHAT.md").read_text()
    assert used and all(f"{name}=" in example and name in guide for name in used), used
