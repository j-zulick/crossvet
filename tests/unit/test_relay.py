"""Agents' requests passed through to the named model, checked against replies recorded from the real APIs
on 2026-11-26 (tests/unit/fixtures; encrypted reasoning shortened, no keys)."""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from crossvet import relay
from crossvet.providers import AccountError, ProviderError, Reply

FIX = Path(__file__).parent / "fixtures"
TOOLS = [{"type": "function", "function": {"name": "lookup_vin", "description": "Look up a VIN.",
                                           "parameters": {"type": "object", "properties": {"vin": {"type": "string"}}}}}]
ASK = [{"role": "system", "content": "You help a Sarasota used-car dealer."},
       {"role": "user", "content": "Prices of VINs 1FTFW1E80MFA12345 and 5J6RW2H89KL004321?"}]


def fixture(name: str):
    return json.loads((FIX / name).read_text())


def recorder(*responses):
    seen, queue = [], list(responses)

    def handle(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return queue.pop(0) if len(queue) > 1 else queue[0]

    return httpx.MockTransport(handle), seen


def sse(events) -> httpx.Response:
    body = "".join(f"data: {json.dumps(e)}\n\n" for e in events) + "data: [DONE]\n\n"
    return httpx.Response(200, text=body, headers={"content-type": "text/event-stream"})


@pytest.fixture(autouse=True)
def keys(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")


# --- OpenAI through the Responses API --------------------------------------------------------------

def test_a_recorded_parallel_tool_call_comes_back_in_chat_shape():
    transport, seen = recorder(httpx.Response(200, json=fixture("responses-tool-call.json")))
    raw, reply = relay.send("openai:gpt-6.1-sol", {"messages": ASK, "tools": TOOLS, "max_tokens": 800}, transport=transport)
    sent = json.loads(seen[0].content)
    assert str(seen[0].url) == "https://api.openai.com/v1/responses"
    assert sent["store"] is False and sent["include"] == ["reasoning.encrypted_content"] and sent["max_output_tokens"] == 800
    assert [c["function"]["name"] for c in reply.tool_calls] == ["lookup_vin", "lookup_vin"]
    assert json.loads(reply.tool_calls[1]["function"]["arguments"]) == {"vin": "5J6RW2H89KL004321"}
    assert raw["choices"][0]["finish_reason"] == "tool_calls" and reply.input_tokens == 103 and reply.output_tokens == 68


def test_the_whole_conversation_is_translated_and_reasoning_goes_back_first():
    reasoning = {"type": "reasoning", "id": "rs_1", "encrypted_content": "gAAA", "summary": []}
    messages = [
        {"role": "developer", "content": "Use tools."},
        {"role": "user", "name": "joe", "content": [{"type": "text", "text": "Price?"},
                                                     {"type": "image_url", "image_url": {"url": "https://x/y.jpg"}}]},
        {"role": "assistant", "content": "Checking both.", "tool_calls": [
            {"id": "call_1", "type": "function", "function": {"name": "lookup_vin", "arguments": "{\"vin\": \"1\"}"}},
            {"id": "call_2", "type": "function", "function": {"name": "lookup_vin", "arguments": "{\"vin\": \"2\"}"}}]},
        {"role": "tool", "tool_call_id": "call_1", "content": [{"type": "text", "text": "{\"price\": 38995}"}]},
        {"role": "tool", "tool_call_id": "call_2", "content": "{\"price\": 27450}"}]
    body = {"model": "gpt-6.1-sol", "messages": messages, "tools": TOOLS, "tool_choice": {"type": "function", "function": {"name": "lookup_vin"}},
            "max_completion_tokens": 300, "reasoning_effort": "high", "parallel_tool_calls": True, "seed": 7, "logprobs": True,
            "response_format": {"type": "json_schema", "json_schema": {"name": "p", "schema": {"type": "object"}}}}
    out, dropped = relay.to_responses_request(body, {"call_1": [reasoning], "call_2": [reasoning]})
    assert dropped == ["logprobs", "seed", "messages[].name"]
    assert out["input"] == [
        {"role": "developer", "content": "Use tools."},
        {"role": "user", "content": [{"type": "input_text", "text": "Price?"}, {"type": "input_image", "image_url": "https://x/y.jpg"}]},
        reasoning,  # once, before the turn that made the calls
        {"role": "assistant", "content": "Checking both."},
        {"type": "function_call", "call_id": "call_1", "name": "lookup_vin", "arguments": "{\"vin\": \"1\"}"},
        {"type": "function_call", "call_id": "call_2", "name": "lookup_vin", "arguments": "{\"vin\": \"2\"}"},
        {"type": "function_call_output", "call_id": "call_1", "output": "{\"price\": 38995}"},
        {"type": "function_call_output", "call_id": "call_2", "output": "{\"price\": 27450}"}]
    assert out["tool_choice"] == {"type": "function", "name": "lookup_vin"} and out["reasoning"] == {"effort": "high"}
    assert out["text"] == {"format": {"type": "json_schema", "name": "p", "schema": {"type": "object"}}}
    assert out["max_output_tokens"] == 300 and out["parallel_tool_calls"] is True
    assert out["tools"][0] == {"type": "function", "name": "lookup_vin", "description": "Look up a VIN.",
                               "parameters": TOOLS[0]["function"]["parameters"], "strict": False}


def test_the_old_functions_format_still_works():
    out, _ = relay.to_responses_request({"model": "m", "functions": [{"name": "f", "parameters": {}}], "function_call": {"name": "f"},
                                         "messages": [{"role": "assistant", "function_call": {"name": "f", "arguments": "{}"}},
                                                      {"role": "function", "name": "f", "content": "done"}]})
    assert out["tools"][0]["name"] == "f" and out["tool_choice"] == {"type": "function", "name": "f"}
    assert out["input"] == [{"type": "function_call", "call_id": "f", "name": "f", "arguments": "{}"},
                            {"type": "function_call_output", "call_id": "f", "output": "done"}]


def test_several_answers_per_request_are_refused_clearly():
    with pytest.raises(ProviderError, match="n > 1"):
        relay.to_responses_request({"model": "m", "messages": [], "n": 2})


def test_reasoning_before_tool_calls_is_kept_for_the_next_turn():
    out = [{"type": "reasoning", "id": "rs_9", "encrypted_content": "gBBB", "summary": [], "status": None},
           {"type": "message", "content": [{"type": "output_text", "text": "Checking."}]},
           {"type": "function_call", "call_id": "call_9", "name": "lookup_vin", "arguments": "{}"}]
    assert relay.state_from(out) == {"call_9": [{"type": "reasoning", "id": "rs_9", "encrypted_content": "gBBB", "summary": []}]}
    assert relay.state_from(fixture("responses-tool-call.json")["output"]) == {}  # no reasoning, nothing kept
    chat = relay.to_chat_completion({"output": out, "status": "completed"})
    assert chat["choices"][0]["message"]["content"] == "Checking." and chat["choices"][0]["finish_reason"] == "tool_calls"


@pytest.mark.parametrize(("status", "reason", "finish"), [
    ("incomplete", "max_output_tokens", "length"), ("incomplete", "content_filter", "content_filter"), ("completed", None, "stop")])
def test_finish_reasons(status, reason, finish):
    data = {"output": [{"type": "message", "content": [{"type": "refusal", "refusal": "No."}]}], "status": status,
            "incomplete_details": {"reason": reason} if reason else None}
    chat = relay.to_chat_completion(data)
    assert chat["choices"][0]["finish_reason"] == finish and chat["choices"][0]["message"]["content"] == "No."


def test_expired_reasoning_is_sent_again_without_it_once():
    stale = httpx.Response(400, json={"error": {"code": "invalid_encrypted_content", "message": "could not be verified"}})
    transport, seen = recorder(stale, httpx.Response(200, json=fixture("responses-tool-call.json")))
    messages = [*ASK, {"role": "assistant", "content": None, "tool_calls": [
        {"id": "call_1", "type": "function", "function": {"name": "lookup_vin", "arguments": "{}"}}]},
        {"role": "tool", "tool_call_id": "call_1", "content": "x"}]
    state = {"call_1": [{"type": "reasoning", "id": "rs_1", "encrypted_content": "old", "summary": []}]}
    _, reply = relay.send("openai:gpt-6.1-sol", {"messages": messages, "tools": TOOLS}, state, transport)
    assert len(seen) == 2 and not any(i.get("type") == "reasoning" for i in json.loads(seen[1].content)["input"])
    assert reply.dropped == ["kept reasoning (expired)"]


def test_other_errors_are_not_resent():
    transport, seen = recorder(httpx.Response(400, json={"error": {"message": "bad tool schema"}}))
    with pytest.raises(ProviderError, match="bad tool schema"):
        relay.send("openai:gpt-6.1-sol", {"messages": ASK, "tools": TOOLS}, transport=transport)
    transport, seen = recorder(httpx.Response(401, text="invalid api key"))
    with pytest.raises(AccountError):
        relay.send("openai:gpt-6.1-sol", {"messages": ASK, "tools": TOOLS}, transport=transport)
    assert len(seen) == 1


def test_a_recorded_streamed_tool_call_becomes_chat_deltas():
    transport, seen = recorder(sse(fixture("responses-stream-tool-call.json")))
    items = list(relay.send_stream("openai:gpt-6-luna", {"messages": ASK, "tools": TOOLS}, transport=transport))
    reply = items[-1]
    deltas = [i["delta"] for i in items[:-1]]
    assert json.loads(seen[0].content)["stream"] is True
    starts = [d["tool_calls"][0] for d in deltas if d.get("tool_calls") and "id" in d["tool_calls"][0]]
    assert [(s["index"], s["function"]["name"]) for s in starts] == [(0, "lookup_vin"), (1, "lookup_vin")]
    assert [json.loads(c["function"]["arguments"])["vin"] for c in reply.tool_calls] == ["1FTFW1E80MFA12345", "5J6RW2H89KL004321"]
    assert items[-2] == {"delta": {}, "finish_reason": "tool_calls"} and reply.stop == "tool_calls" and reply.output_tokens > 0


def test_a_recorded_streamed_answer_after_tool_results():
    transport, _ = recorder(sse(fixture("responses-stream-after-tool.json")))
    items = list(relay.send_stream("openai:gpt-6.1-sol", {"messages": ASK, "tools": TOOLS}, transport=transport))
    reply = items[-1]
    assert "$38,995" in reply.text and "".join(i["delta"].get("content", "") for i in items[:-1]) == reply.text
    assert reply.stop == "stop" and reply.input_tokens == 237


def test_a_stream_error_before_output_is_an_error_and_after_output_ends_the_stream():
    transport, _ = recorder(httpx.Response(500, text="oops"))
    with pytest.raises(ProviderError, match="HTTP 500"):
        list(relay.send_stream("openai:gpt-6-luna", {"messages": ASK, "tools": TOOLS}, transport=transport))
    events = [{"type": "response.output_text.delta", "delta": "Part"}, {"type": "response.failed", "response": {"error": {"message": "x"}}}]
    transport, _ = recorder(sse(events))
    items = list(relay.send_stream("openai:gpt-6-luna", {"messages": ASK, "tools": TOOLS}, transport=transport))
    assert items[-1].stop == "error" and items[-1].text == "Part"


# --- Anthropic and the chat-completions providers -------------------------------------------------

def test_a_recorded_anthropic_streamed_tool_call():
    transport, seen = recorder(sse(fixture("anthropic-compat-stream-tool-call.json")))
    items = list(relay.send_stream("anthropic:claude-sonnet-5-5", {"messages": ASK, "tools": TOOLS, "max_completion_tokens": 400},
                                   transport=transport))
    reply = items[-1]
    sent = json.loads(seen[0].content)
    assert str(seen[0].url) == "https://api.anthropic.com/v1/chat/completions" and seen[0].headers["authorization"] == "Bearer sk-ant-test"
    assert sent["max_tokens"] == 400 and sent["stream"] is True and sent["stream_options"] == {"include_usage": True}
    assert reply.tool_calls and all(c["function"]["name"] == "lookup_vin" for c in reply.tool_calls)
    assert all("vin" in json.loads(c["function"]["arguments"]) for c in reply.tool_calls)
    assert reply.stop == "tool_calls" and (reply.input_tokens, reply.output_tokens) == (455, 122)


def test_anthropic_whole_reply_and_openrouter_cost(monkeypatch):
    call = {"id": "t", "type": "function", "function": {"name": "lookup_vin", "arguments": "{}"}}
    transport, seen = recorder(httpx.Response(200, json={"model": "claude-opus-5-5", "choices": [
        {"message": {"content": None, "tool_calls": [call]}, "finish_reason": "tool_calls"}], "usage": {"prompt_tokens": 30, "completion_tokens": 9}}))
    raw, reply = relay.send("anthropic:claude-opus-5-5", {"messages": ASK, "tools": TOOLS, "stream": True}, transport=transport)
    assert "stream" not in json.loads(seen[0].content) and reply.tool_calls == [call] and reply.input_tokens == 30
    monkeypatch.setenv("OPENROUTER_API_KEY", "or")
    transport, seen = recorder(httpx.Response(200, json={"choices": [{"message": {"content": "hi"}}], "usage": {"cost": 0.002}}))
    _, reply = relay.send("openrouter:x/y", {"messages": ASK, "tools": TOOLS}, transport=transport)
    assert reply.cost == 0.002 and json.loads(seen[0].content)["usage"] == {"include": True}


def test_reply_carries_dropped_and_state_defaults():
    assert Reply("x", "m").dropped == [] and Reply("x", "m").state == {}
