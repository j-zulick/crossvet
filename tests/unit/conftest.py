"""Shared fixtures: every unit test is offline. Models are replaced by a scripted fake."""

from __future__ import annotations

import os

import pytest

from crossvet import server
from crossvet.config import parse
from crossvet.core import Crossvet
from crossvet.providers import Reply
from crossvet.store import Store

KEYS = ("OPENAI_API_KEY", "ANTHROPIC_API_KEY", "GOOGLE_API_KEY", "XAI_API_KEY", "OPENROUTER_API_KEY", "LOCAL_BASE_URL",
        "LOCAL_API_KEY", "OLLAMA_BASE_URL", "CROSSVET_CONFIG", "CROSSVET_DB", "CROSSVET_TOKEN")

SETTINGS = {
    "default_model": "sonnet",
    "models": ["anthropic:claude-opus-5-5", "openai:gpt-6.1-sol", "openai:gpt-6-luna"],
    "names": {"claude": "anthropic:claude-opus-5-5", "sonnet": "anthropic:claude-sonnet-5-5", "gpt": "openai:gpt-6.1-sol",
              "luna": "openai:gpt-6-luna"},
    "limits": {"max_usd_per_day": 0, "max_usd_per_call": 0, "max_output_tokens": 1000},
}


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch, tmp_path):
    """No real keys, settings files or logs reach a test; the working folder is empty."""
    for key in KEYS + tuple(k for k in os.environ if k.startswith("CROSSVET_")):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setattr("crossvet.config.HOME", tmp_path / "home" / ".config" / "crossvet")
    monkeypatch.setattr("crossvet.cli.HOME", tmp_path / "home" / ".config" / "crossvet")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(server, "FAIL_DELAY_SECONDS", 0.0)


class FakeModels:
    """Scripted answers per model: a string, a Reply, an Exception, or a function of the messages."""

    def __init__(self) -> None:
        self.script: dict[str, list] = {}
        self.calls: list[tuple[str, list[dict]]] = []
        self.relayed: list[tuple[str, dict]] = []

    def on(self, model: str, *answers) -> FakeModels:
        self.script.setdefault(model, []).extend(answers)
        return self

    def _next(self, model: str, messages: list[dict]) -> Reply:
        queue = self.script.get(model) or ["ok"]
        item = queue.pop(0) if len(queue) > 1 else queue[0]
        if isinstance(item, Exception):
            raise item
        if callable(item):
            item = item(messages)
        if isinstance(item, Reply):
            return item
        return Reply(text=str(item), model=model, input_tokens=100, output_tokens=50, seconds=0.1)

    def stream(self, model: str, messages: list[dict], max_tokens: int):
        self.calls.append((model, messages))
        reply = self._next(model, messages)
        if reply.text:
            for i, word in enumerate(reply.text.split(" ")):
                yield word if i == 0 else " " + word
        yield reply

    def relay(self, model: str, body: dict):
        self.relayed.append((model, body))
        reply = self._next(model, body["messages"])
        message = {"role": "assistant", "content": reply.text or None}
        if reply.tool_calls:
            message["tool_calls"] = reply.tool_calls
        raw = {"choices": [{"message": message, "finish_reason": "tool_calls" if reply.tool_calls else "stop"}],
               "usage": {"prompt_tokens": reply.input_tokens, "completion_tokens": reply.output_tokens}}
        return raw, reply


@pytest.fixture
def fake() -> FakeModels:
    return FakeModels()


@pytest.fixture
def make(fake):
    """Build a Crossvet with the test settings (overridable), an in-memory log and the fake models."""

    def build(**changes) -> Crossvet:
        data = {**SETTINGS, **{k: v for k, v in changes.items() if k != "limits"}}
        data["limits"] = {**SETTINGS["limits"], **changes.get("limits", {})}
        return Crossvet(parse(data, "test"), Store(), streamer=fake.stream, relayer=fake.relay)

    return build


@pytest.fixture
def cv(make) -> Crossvet:
    return make()
