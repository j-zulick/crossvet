"""Answers streamed piece by piece: providers, the hub's fallback rule, and the server."""

from __future__ import annotations

import json

import httpx
import pytest
from starlette.testclient import TestClient

from crossvet.chat import providers
from crossvet.chat.config import parse
from crossvet.chat.hub import Hub
from crossvet.chat.memory import Memory
from crossvet.chat.providers import ProviderError, Reply
from crossvet.chat.record import Recorder
from crossvet.chat.server import create_app

from .conftest import CONFIG


def sse(*events: dict | str) -> bytes:
    lines = [f"data: {e if isinstance(e, str) else json.dumps(e)}\n\n" for e in events]
    return "".join(lines).encode()


def openai_chunks(*pieces: str, finish: str = "stop", cost: float | None = 0.002) -> bytes:
    events: list[dict | str] = [{"model": "openai/gpt-x", "choices": [{"delta": {"content": p}, "finish_reason": None}]}
                                for p in pieces]
    events.append({"choices": [{"delta": {}, "finish_reason": finish}]})
    usage = {"prompt_tokens": 12, "completion_tokens": 7, **({"cost": cost} if cost is not None else {})}
    events.append({"choices": [], "usage": usage})
    events.append("[DONE]")
    return sse(*events)


def transport(body: bytes, status: int = 200, seen: dict | None = None) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        if seen is not None:
            seen["body"] = json.loads(request.content)
            seen["url"] = str(request.url)
        return httpx.Response(status, content=body, headers={"content-type": "text/event-stream"})
    return httpx.MockTransport(handler)


def test_openai_style_stream_yields_pieces_then_reply(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    seen: dict = {}
    out = list(providers.stream("openrouter:openai/gpt-x", [{"role": "user", "content": "hi"}], 100,
                                transport(openai_chunks("Hel", "lo"), seen=seen)))
    assert out[:2] == ["Hel", "lo"]
    reply = out[-1]
    assert isinstance(reply, Reply) and reply.text == "Hello" and reply.cost == 0.002
    assert (reply.input_tokens, reply.output_tokens, reply.truncated) == (12, 7, False)
    assert seen["body"]["stream"] is True and seen["body"]["usage"] == {"include": True}
    assert seen["body"]["stream_options"] == {"include_usage": True}


def test_cut_off_stream_is_marked_truncated(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    out = list(providers.stream("openai:gpt-x", [{"role": "user", "content": "hi"}], 5,
                                transport(openai_chunks("abc", finish="length"))))
    assert out[-1].truncated


def test_anthropic_stream(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    body = sse({"type": "message_start", "message": {"usage": {"input_tokens": 9}}},
               {"type": "content_block_delta", "delta": {"type": "text_delta", "text": "Bon"}},
               {"type": "content_block_delta", "delta": {"type": "text_delta", "text": "jour"}},
               {"type": "message_delta", "delta": {"stop_reason": "end_turn"}, "usage": {"output_tokens": 3}})
    out = list(providers.stream("anthropic:claude-x", [{"role": "system", "content": "s"}, {"role": "user", "content": "hi"}],
                                100, transport(body)))
    assert out[:2] == ["Bon", "jour"] and out[-1].text == "Bonjour"
    assert (out[-1].input_tokens, out[-1].output_tokens, out[-1].raw_stop) == (9, 3, "end_turn")


def test_http_error_before_any_text_raises(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    with pytest.raises(ProviderError, match="HTTP 500"):
        list(providers.stream("openai:gpt-x", [{"role": "user", "content": "hi"}], 100, transport(b"boom", status=500)))


def test_missing_key_raises_before_streaming(monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    with pytest.raises(ProviderError, match="OPENROUTER_API_KEY is not set"):
        list(providers.stream("openrouter:openai/gpt-x", [{"role": "user", "content": "hi"}], 100, transport(b"")))


def scripted_streamer(script: dict[str, object]):
    """A streamer for the hub: each model gets a list of pieces, an exception, or pieces then a broken stop."""
    calls: list[str] = []

    def stream(model: str, messages, max_tokens):
        calls.append(model)
        item = script[model]
        if isinstance(item, Exception):
            raise item
        pieces, stop = item if isinstance(item, tuple) else (item, "stop")
        yield from pieces
        yield Reply(text="".join(pieces), model=model, input_tokens=10, output_tokens=5, raw_stop=stop,
                    truncated=stop == "length")
    stream.calls = calls  # type: ignore[attr-defined]
    return stream


def stream_hub(script: dict[str, object]) -> tuple[Hub, object]:
    streamer = scripted_streamer(script)
    hub = Hub(config=parse(CONFIG, "test"), memory=Memory(":memory:"), recorder=Recorder(), streamer=streamer,
              caller=lambda *a: Reply(text="unused", model="x"))
    return hub, streamer


def test_hub_falls_back_when_a_model_fails_before_any_text():
    hub, streamer = stream_hub({"anthropic:big": ProviderError("HTTP 503"), "openai:big": ["fi", "ne"]})
    out = list(hub.ask_stream("Fix the race condition in this Go worker pool", slot="strong"))
    assert out[:2] == ["fi", "ne"]
    answer = out[-1]
    assert answer.model == "openai:big" and answer.text == "fine"
    assert [a.ok for a in answer.attempts] == [False, True]
    assert streamer.calls == ["anthropic:big", "openai:big"]


def test_hub_does_not_switch_models_after_text_was_sent():
    hub, streamer = stream_hub({"anthropic:big": (["partial"], "length"), "openai:big": ["unused"]})
    out = list(hub.ask_stream("Fix the race condition in this Go worker pool", slot="strong"))
    answer = out[-1]
    assert out[0] == "partial" and answer.text == "partial"
    assert answer.attempts[0].problem == "stopped at the output limit"
    assert streamer.calls == ["anthropic:big"]


def test_hub_skips_an_empty_stream_for_the_next_model():
    hub, streamer = stream_hub({"anthropic:big": [], "openai:big": ["ok"]})
    out = list(hub.ask_stream("Fix the race condition in this Go worker pool", slot="strong"))
    assert out[-1].model == "openai:big" and streamer.calls == ["anthropic:big", "openai:big"]


def test_streamed_turns_are_saved_like_any_other():
    hub, _ = stream_hub({"anthropic:big": ["saved"], "openai:big": ["x"]})
    out = list(hub.ask_stream("Fix the race condition in this Go worker pool", slot="strong", author="hermes"))
    answer = out[-1]
    assert answer.turn_id and hub.memory.last_answer(answer.thread).content == "saved"


def test_server_streams_piece_by_piece_and_closes_with_usage():
    hub, _ = stream_hub({"anthropic:big": ["one ", "two ", "three"], "openai:big": ["x"]})
    client = TestClient(create_app(hub))
    text = client.post("/v1/chat/completions", json={"model": "crossvet/strong", "stream": True,
                                                     "messages": [{"role": "user", "content": "go"}]}).text
    chunks = [json.loads(part.removeprefix("data: ")) for part in text.strip().split("\n\n") if part != "data: [DONE]"]
    contents = [c["choices"][0]["delta"].get("content") for c in chunks]
    assert contents[1:4] == ["one ", "two ", "three"]
    assert chunks[-1]["choices"][0]["finish_reason"] == "stop" and chunks[-1]["model"] == "anthropic:big"
    assert chunks[-1]["usage"]["completion_tokens"] == 5 and "crossvet" in chunks[-1]
    assert text.rstrip().endswith("data: [DONE]")


def test_server_returns_an_http_error_when_nothing_was_sent():
    hub, _ = stream_hub({"anthropic:big": ProviderError("HTTP 503"), "openai:big": ProviderError("HTTP 503")})
    client = TestClient(create_app(hub))
    response = client.post("/v1/chat/completions", json={"model": "crossvet/strong", "stream": True,
                                                         "messages": [{"role": "user", "content": "go"}]})
    assert response.status_code == 502 and response.json()["error"]["type"] == "upstream_error"


def test_a_server_that_ignores_stream_still_answers(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    whole = json.dumps({"choices": [{"message": {"content": "in one piece"}, "finish_reason": "stop"}],
                        "usage": {"prompt_tokens": 3, "completion_tokens": 4}}).encode()

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=whole, headers={"content-type": "application/json"})
    out = list(providers.stream("openai:gpt-x", [{"role": "user", "content": "hi"}], 100, httpx.MockTransport(handler)))
    assert out[0] == "in one piece" and out[-1].output_tokens == 4
