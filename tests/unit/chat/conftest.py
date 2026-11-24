"""Shared fixtures: every test is offline. Models are replaced by a scripted fake."""

from __future__ import annotations

import pytest

from open_deep_research.chat.config import parse
from open_deep_research.chat.hub import Hub
from open_deep_research.chat.memory import Memory
from open_deep_research.chat.providers import ProviderError, Reply
from open_deep_research.chat.record import Recorder

CONFIG = {
    "slots": {
        "quick": ["openai:small", "anthropic:small"],
        "balanced": ["openai:mid"],
        "strong": ["anthropic:big", "openai:big"],
        "fresh": ["xai:grok"],
        "long": ["google:wide"],
        "reviewer": ["openai:big"],
    },
    "limits": {"max_usd_per_day": 0, "max_usd_per_call": 0, "max_output_tokens": 1000},
    "models": {
        "openai:small": {"context": 8000, "input": 0.1, "output": 0.5},
        "anthropic:small": {"context": 8000, "input": 0.1, "output": 0.5},
        "openai:mid": {"context": 8000, "input": 1, "output": 5},
        "anthropic:big": {"context": 8000, "input": 4, "output": 20},
        "openai:big": {"context": 8000, "input": 2, "output": 10},
        "google:wide": {"context": 1_000_000, "input": 1, "output": 5},
    },
}


class FakeModels:
    """Scripted replies per model: a string, a Reply, an Exception, or a function of the messages."""

    def __init__(self) -> None:
        self.script: dict[str, list] = {}
        self.calls: list[tuple[str, list[dict[str, str]]]] = []

    def set(self, model: str, *replies) -> None:
        self.script[model] = list(replies)

    def __call__(self, model: str, messages: list[dict[str, str]], max_tokens: int) -> Reply:
        self.calls.append((model, messages))
        queue = self.script.get(model)
        item = (queue.pop(0) if len(queue) > 1 else queue[0]) if queue else f"answer from {model}"
        if callable(item):
            item = item(messages)
        if isinstance(item, Exception):
            raise item
        if isinstance(item, Reply):
            item.model = model
            return item
        return Reply(text=item, model=model, input_tokens=100, output_tokens=50)


@pytest.fixture
def models() -> FakeModels:
    return FakeModels()


@pytest.fixture
def hub(models: FakeModels) -> Hub:
    return Hub(config=parse(CONFIG, "test"), memory=Memory(":memory:"), caller=models, recorder=Recorder())


@pytest.fixture
def provider_error():
    return ProviderError
