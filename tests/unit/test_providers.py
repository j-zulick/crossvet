"""Vendor calls, checked against recorded request and reply shapes (no network)."""

from __future__ import annotations

import json

import httpx
import pytest

from crossvet import providers
from crossvet.providers import AccountError, ProviderError, Reply


def recorder(handler):
    seen = []

    def handle(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return handler(request)

    return httpx.MockTransport(handle), seen


def sse(*events) -> httpx.Response:
    body = "".join(f"data: {json.dumps(e)}\n\n" for e in events) + "data: [DONE]\n\n"
    return httpx.Response(200, text=body, headers={"content-type": "text/event-stream"})


def test_openai_streams_with_its_own_limit_field(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    transport, seen = recorder(lambda r: sse(
        {"model": "gpt-6-luna-2026", "choices": [{"delta": {"content": "Low "}}]},
        {"choices": [{"delta": {"content": "mileage."}, "finish_reason": "stop"}]},
        {"choices": [], "usage": {"prompt_tokens": 20, "completion_tokens": 3}}))
    items = list(providers.stream("openai:gpt-6-luna", [{"role": "user", "content": "q"}], 50, transport))
    assert items[:2] == ["Low ", "mileage."]
    reply = items[-1]
    assert (reply.text, reply.input_tokens, reply.output_tokens, reply.served_by) == ("Low mileage.", 20, 3, "gpt-6-luna-2026")
    body = json.loads(seen[0].content)
    assert body["max_completion_tokens"] == 50 and "max_tokens" not in body and body["model"] == "gpt-6-luna"
    assert seen[0].headers["authorization"] == "Bearer sk-test"


def test_anthropic_streams_from_its_messages_api(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    transport, seen = recorder(lambda r: sse(
        {"type": "message_start", "message": {"model": "claude-opus-5-5", "usage": {"input_tokens": 12}}},
        {"type": "content_block_delta", "delta": {"type": "text_delta", "text": "Yes."}},
        {"type": "message_delta", "delta": {"stop_reason": "end_turn"}, "usage": {"output_tokens": 2}}))
    reply = providers.call("anthropic:claude-opus-5-5",
                           [{"role": "system", "content": "Be brief."}, {"role": "user", "content": "q"}], 100, transport)
    assert (reply.text, reply.input_tokens, reply.output_tokens) == ("Yes.", 12, 2)
    body = json.loads(seen[0].content)
    assert seen[0].url == providers.ANTHROPIC_URL and body["system"] == "Be brief." and body["max_tokens"] == 100
    assert body["messages"] == [{"role": "user", "content": "q"}] and seen[0].headers["x-api-key"] == "sk-ant-test"


def test_openrouter_reports_real_cost(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "or-test")
    transport, seen = recorder(lambda r: sse({"choices": [{"delta": {"content": "x"}}], "usage": {"cost": 0.0021}}))
    assert providers.call("openrouter:openai/gpt-x", [{"role": "user", "content": "q"}], 10, transport).cost == 0.0021
    assert json.loads(seen[0].content)["usage"] == {"include": True} and seen[0].headers["x-title"] == "Crossvet"


def test_a_server_that_ignores_stream_still_works(monkeypatch):
    transport, _ = recorder(lambda r: httpx.Response(200, json={
        "choices": [{"message": {"content": "whole"}, "finish_reason": "length"}], "usage": {"prompt_tokens": 1}}))
    items = list(providers.stream("ollama:gemma3", [{"role": "user", "content": "q"}], 10, transport))
    assert items[0] == "whole" and items[-1].truncated


@pytest.mark.parametrize(("status", "text", "kind"), [
    (401, "bad key", AccountError), (402, "pay", AccountError), (429, "You exceeded your current quota", AccountError),
    (429, "rate limited, slow down", ProviderError), (500, "oops", ProviderError)])
def test_account_refusals_are_told_apart_from_other_errors(monkeypatch, status, text, kind):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    transport, _ = recorder(lambda r: httpx.Response(status, text=text))
    with pytest.raises(ProviderError) as raised:
        providers.call("openai:gpt-6-luna", [{"role": "user", "content": "q"}], 10, transport)
    assert type(raised.value) is kind


def test_a_missing_key_is_named():
    with pytest.raises(ProviderError, match="ANTHROPIC_API_KEY is not set"):
        providers.call("anthropic:claude-opus-5-5", [{"role": "user", "content": "q"}])
    with pytest.raises(ProviderError, match="OPENAI_API_KEY is not set"):
        providers.call("openai:gpt-6-luna", [{"role": "user", "content": "q"}])


def test_passthrough_sends_anthropic_tools_to_its_openai_compatible_endpoint(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    call = {"id": "t", "type": "function", "function": {"name": "lookup_vin", "arguments": "{}"}}
    transport, seen = recorder(lambda r: httpx.Response(200, json={
        "model": "claude-opus-5-5", "choices": [{"message": {"content": None, "tool_calls": [call]}, "finish_reason": "tool_calls"}],
        "usage": {"prompt_tokens": 30, "completion_tokens": 9}}))
    body = {"model": "x", "messages": [{"role": "user", "content": "q"}], "tools": [{"type": "function"}], "stream": True,
            "max_completion_tokens": 200}
    raw, reply = providers.passthrough("anthropic:claude-opus-5-5", body, transport)
    sent = json.loads(seen[0].content)
    assert str(seen[0].url) == providers.ANTHROPIC_OPENAI_URL and seen[0].headers["authorization"] == "Bearer sk-ant-test"
    assert sent["model"] == "claude-opus-5-5" and sent["max_tokens"] == 200 and "stream" not in sent and sent["tools"]
    assert reply.tool_calls == [call] and reply.input_tokens == 30 and raw["choices"][0]["finish_reason"] == "tool_calls"


def test_openai_tool_requests_go_through_the_responses_api(monkeypatch):
    """OpenAI's current models refuse tools on chat completions (checked live on 2026-11-26)."""
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    transport, seen = recorder(lambda r: httpx.Response(200, json={
        "id": "resp_1", "model": "gpt-6.1-sol-2026", "created_at": 1,
        "output": [{"type": "reasoning", "summary": []},
                   {"type": "function_call", "call_id": "call_9", "name": "lookup_vin", "arguments": "{\"vin\": \"1\"}"}],
        "usage": {"input_tokens": 80, "output_tokens": 12, "total_tokens": 92}}))
    body = {"model": "x", "max_tokens": 300, "tool_choice": {"type": "function", "function": {"name": "lookup_vin"}},
            "messages": [{"role": "system", "content": "Use tools."},
                         {"role": "user", "content": [{"type": "text", "text": "Price?"},
                                                      {"type": "image_url", "image_url": {"url": "https://x/y.jpg"}}]},
                         {"role": "assistant", "content": None,
                          "tool_calls": [{"id": "call_1", "type": "function", "function": {"name": "lookup_vin", "arguments": "{}"}}]},
                         {"role": "tool", "tool_call_id": "call_1", "content": "{\"price\": 38995}"}],
            "tools": [{"type": "function", "function": {"name": "lookup_vin", "parameters": {"type": "object"}}}]}
    raw, reply = providers.passthrough("openai:gpt-6.1-sol", body, transport)
    sent = json.loads(seen[0].content)
    assert str(seen[0].url) == "https://api.openai.com/v1/responses"
    assert sent["model"] == "gpt-6.1-sol" and sent["max_output_tokens"] == 300 and sent["store"] is False
    assert sent["tools"] == [{"type": "function", "name": "lookup_vin", "description": "", "parameters": {"type": "object"},
                              "strict": False}]
    assert sent["tool_choice"] == {"type": "function", "name": "lookup_vin"}
    assert sent["input"] == [
        {"role": "system", "content": "Use tools."},
        {"role": "user", "content": [{"type": "input_text", "text": "Price?"}, {"type": "input_image", "image_url": "https://x/y.jpg"}]},
        {"type": "function_call", "call_id": "call_1", "name": "lookup_vin", "arguments": "{}"},
        {"type": "function_call_output", "call_id": "call_1", "output": "{\"price\": 38995}"}]
    assert raw["choices"][0]["finish_reason"] == "tool_calls" and raw["usage"]["prompt_tokens"] == 80
    assert reply.tool_calls == [{"id": "call_9", "type": "function", "function": {"name": "lookup_vin", "arguments": "{\"vin\": \"1\"}"}}]
    assert (reply.input_tokens, reply.output_tokens, reply.served_by) == (80, 12, "gpt-6.1-sol-2026")


def test_a_responses_text_answer_and_a_cut_off_answer():
    done = providers.to_chat_completion({"output": [{"type": "message", "content": [{"type": "output_text", "text": "$38,995"}]}]})
    assert done["choices"][0]["message"] == {"role": "assistant", "content": "$38,995"} and done["choices"][0]["finish_reason"] == "stop"
    cut = providers.to_chat_completion({"output": [], "incomplete_details": {"reason": "max_output_tokens"}})
    assert cut["choices"][0]["finish_reason"] == "length"
    with pytest.raises(ProviderError):
        providers.to_chat_completion({"error": "x"})
    assert providers.to_responses_request({"model": "m", "messages": [], "reasoning_effort": "low",
                                           "response_format": {"type": "json_object"}})["reasoning"] == {"effort": "low"}


def test_images_are_converted_for_anthropic():
    system, turns = providers.anthropic_turns([{"role": "user", "content": [
        {"type": "text", "text": "What trim is this?"},
        {"type": "image_url", "image_url": {"url": "data:image/png;base64,AAAA"}},
        {"type": "image_url", "image_url": {"url": "https://example.com/truck.jpg"}}]}])
    assert system == "" and turns[0]["content"] == [
        {"type": "text", "text": "What trim is this?"},
        {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": "AAAA"}},
        {"type": "image", "source": {"type": "url", "url": "https://example.com/truck.jpg"}}]
    with pytest.raises(ProviderError, match="not supported"):
        providers.anthropic_turns([{"role": "user", "content": [{"type": "input_audio"}]}])


def test_model_names_need_a_known_provider():
    assert providers.split("openrouter:anthropic/claude") == ("openrouter", "anthropic/claude")
    for bad in ("gpt-6", "nope:x", "openai:"):
        with pytest.raises(ProviderError):
            providers.split(bad)


def test_ollama_needs_no_key_and_local_needs_an_address(monkeypatch):
    assert providers.available("ollama") and not providers.available("local")
    monkeypatch.setenv("LOCAL_BASE_URL", "http://127.0.0.1:1234/v1")
    assert providers.available("local")


def test_reply_defaults():
    assert Reply("x", "m").tool_calls == []
