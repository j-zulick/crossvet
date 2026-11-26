"""Pass an agent's whole request (tools, tool results, settings) to the model it named.

Agents such as Hermes send OpenAI chat-completions requests with ``tools`` and ``role: "tool"``
results. Crossvet keeps that shape for the agent and talks to each vendor the way it requires:

- OpenAI: the Responses API. OpenAI's current models refuse tools on chat completions (checked live
  on 2026-11-26), so the request and the reply are translated both ways. Requests are sent with
  ``store: false``; the model's encrypted reasoning is kept locally, keyed by tool-call id, and sent
  back with the tool results, so a reasoning model keeps its chain of thought across tool steps.
- Anthropic: its OpenAI-compatible endpoint, which takes tools in the chat-completions shape.
- Google, xAI, OpenRouter, Ollama, local servers: chat completions, unchanged.

Both a whole reply (:func:`send`) and a stream (:func:`send_stream`) are supported. Fields the
Responses API has no place for are dropped and reported in ``Reply.dropped``, never silently.
"""

from __future__ import annotations

import json
import time
from collections.abc import Iterator
from typing import Any

import httpx

from crossvet.providers import (
    ANTHROPIC_OPENAI_URL,
    ProviderError,
    Reply,
    _anthropic_key,
    _client,
    _endpoint,
    _post,
    http_error,
    split,
    text_of,
)

# Chat-completions fields the Responses translation carries over; anything else is dropped and reported.
CARRIED = {"model", "messages", "tools", "tool_choice", "functions", "function_call", "max_tokens",
           "max_completion_tokens", "reasoning_effort", "temperature", "top_p", "parallel_tool_calls",
           "response_format", "metadata", "service_tier", "stream", "stream_options", "store", "n"}
REASONING_INCLUDE = ["reasoning.encrypted_content"]
STALE_REASONING = "invalid_encrypted_content"  # OpenAI's code when kept reasoning can't be used any more

State = dict[str, list[dict[str, Any]]]  # tool-call id -> the reasoning items that came before it


# --- requests ------------------------------------------------------------------------------------

def _parts(content: Any, role: str) -> Any:
    """Chat-style content (a string or parts) as Responses-API content."""
    if not isinstance(content, list):
        return text_of(content)
    kind = "output_text" if role == "assistant" else "input_text"
    parts = []
    for part in content:
        if not isinstance(part, dict):
            continue
        if part.get("type") in ("text", "input_text", "output_text", "refusal"):
            parts.append({"type": kind, "text": str(part.get("text") or part.get("refusal") or "")})
        elif part.get("type") == "image_url" and role != "assistant":
            parts.append({"type": "input_image", "image_url": str((part.get("image_url") or {}).get("url", ""))})
        else:
            raise ProviderError(f"Crossvet sends text and images to OpenAI with tools; a {part.get('type')!r} part "
                                "is not supported")
    return parts


def _tool(spec: dict[str, Any]) -> dict[str, Any] | None:
    fn = spec.get("function") if spec.get("type") == "function" else spec
    if not isinstance(fn, dict) or not fn.get("name"):
        return None
    return {"type": "function", "name": fn["name"], "description": fn.get("description", ""),
            "parameters": fn.get("parameters") or {"type": "object", "properties": {}},
            "strict": bool(fn.get("strict", False))}


def to_responses_request(body: dict[str, Any], state: State | None = None) -> tuple[dict[str, Any], list[str]]:
    """Turn a chat-completions request into a Responses-API request; return it and the dropped field names."""
    state = state or {}
    dropped = sorted(k for k in body if k not in CARRIED)
    if int(body.get("n") or 1) > 1:
        raise ProviderError("n > 1 (several answers per request) is not supported for OpenAI requests with tools")
    items: list[dict[str, Any]] = []
    sent_reasoning: set[str] = set()
    for m in body.get("messages") or []:
        role = str(m.get("role"))
        if m.get("name") and "messages[].name" not in dropped:
            dropped.append("messages[].name")
        if role == "tool":
            items.append({"type": "function_call_output", "call_id": str(m.get("tool_call_id", "")),
                          "output": text_of(m.get("content"))})
            continue
        if role == "function":  # the old single-function format
            items.append({"type": "function_call_output", "call_id": str(m.get("name", "")), "output": text_of(m.get("content"))})
            continue
        calls = list(m.get("tool_calls") or [])
        if m.get("function_call"):
            fc = m["function_call"]
            calls.append({"id": str(fc.get("name", "")), "function": fc})
        if role == "assistant":
            for call in calls:  # the reasoning that led to these calls goes back first, once
                for item in state.get(str(call.get("id", "")), []):
                    if item.get("id") not in sent_reasoning:
                        sent_reasoning.add(str(item.get("id")))
                        items.append(item)
        content = _parts(m.get("content"), role)
        if content:
            items.append({"role": role, "content": content})
        for call in calls:
            fn = call.get("function") or {}
            items.append({"type": "function_call", "call_id": str(call.get("id", "")), "name": str(fn.get("name", "")),
                          "arguments": str(fn.get("arguments") or "{}")})
    out: dict[str, Any] = {"model": body["model"], "input": items, "store": False, "include": REASONING_INCLUDE}
    tools = [t for t in (_tool(s) for s in [*(body.get("tools") or []), *(body.get("functions") or [])]) if t]
    if tools:
        out["tools"] = tools
    choice = body.get("tool_choice", body.get("function_call"))
    if isinstance(choice, dict):
        out["tool_choice"] = {"type": "function", "name": (choice.get("function") or choice).get("name", "")}
    elif choice:
        out["tool_choice"] = choice
    limit = body.get("max_completion_tokens", body.get("max_tokens"))
    if limit:
        out["max_output_tokens"] = int(limit)
    if body.get("reasoning_effort"):
        out["reasoning"] = {"effort": body["reasoning_effort"]}
    for key in ("temperature", "top_p", "parallel_tool_calls", "metadata", "service_tier"):
        if key in body:
            out[key] = body[key]
    fmt = body.get("response_format") or {}
    if fmt.get("type") == "json_object":
        out["text"] = {"format": {"type": "json_object"}}
    elif fmt.get("type") == "json_schema":
        out["text"] = {"format": {"type": "json_schema", **(fmt.get("json_schema") or {})}}
    return out, dropped


def without_reasoning(request: dict[str, Any]) -> dict[str, Any]:
    """Return the same request with the kept reasoning items taken out."""
    return {**request, "input": [i for i in request["input"] if i.get("type") != "reasoning"]}


# --- replies -------------------------------------------------------------------------------------

def _finish(status: str, details: dict[str, Any] | None, calls: bool) -> str:
    if calls:
        return "tool_calls"
    reason = (details or {}).get("reason")
    if status == "incomplete" and reason == "max_output_tokens":
        return "length"
    if status == "incomplete" and reason == "content_filter":
        return "content_filter"
    return "stop"


def state_from(output: list[dict[str, Any]]) -> State:
    """Map each tool call in a Responses output to the reasoning items that came before it in the same turn."""
    reasoning = [i for i in output if i.get("type") == "reasoning" and i.get("encrypted_content")]
    keep = [{k: v for k, v in i.items() if k in ("type", "id", "encrypted_content", "summary")} for i in reasoning]
    return {str(i.get("call_id")): keep for i in output if i.get("type") == "function_call"} if keep else {}


def to_chat_completion(data: dict[str, Any]) -> dict[str, Any]:
    """Turn a Responses-API reply into a chat-completions reply."""
    if "output" not in data:
        raise ProviderError("unexpected reply shape from the OpenAI Responses API")
    text: list[str] = []
    calls: list[dict[str, Any]] = []
    for item in data.get("output") or []:
        if item.get("type") == "message":
            text += [str(c.get("text") or c.get("refusal") or "") for c in item.get("content") or []
                     if c.get("type") in ("output_text", "refusal")]
        elif item.get("type") == "function_call":
            calls.append({"id": str(item.get("call_id", "")), "type": "function",
                          "function": {"name": str(item.get("name", "")), "arguments": str(item.get("arguments") or "{}")}})
    message: dict[str, Any] = {"role": "assistant", "content": "".join(text) or None}
    if calls:
        message["tool_calls"] = calls
    usage = data.get("usage") or {}
    return {"id": str(data.get("id", "")), "object": "chat.completion", "created": int(data.get("created_at") or time.time()),
            "model": str(data.get("model") or ""),
            "choices": [{"index": 0, "message": message,
                         "finish_reason": _finish(str(data.get("status", "")), data.get("incomplete_details"), bool(calls))}],
            "usage": {"prompt_tokens": int(usage.get("input_tokens", 0) or 0),
                      "completion_tokens": int(usage.get("output_tokens", 0) or 0),
                      "total_tokens": int(usage.get("total_tokens", 0) or 0)}}


def _summary(data: dict[str, Any], model: str) -> Reply:
    choice = data["choices"][0]
    message = choice.get("message") or {}
    usage = data.get("usage") or {}
    cost = usage.get("cost")
    return Reply(text=str(message.get("content") or ""), model=model, input_tokens=int(usage.get("prompt_tokens", 0) or 0),
                 output_tokens=int(usage.get("completion_tokens", 0) or 0),
                 cost=float(cost) if isinstance(cost, (int, float)) else None, stop=str(choice.get("finish_reason") or ""),
                 truncated=choice.get("finish_reason") == "length", served_by=str(data.get("model") or ""),
                 tool_calls=list(message.get("tool_calls") or []))


# --- the wire ------------------------------------------------------------------------------------

def _target(model: str, body: dict[str, Any], state: State | None) -> tuple[str, str, dict[str, str], dict[str, Any], list[str]]:
    """Return (kind, url, headers, request, dropped) for a model: kind is "responses" or "chat"."""
    provider, name = split(model)
    sent = {k: v for k, v in body.items() if k not in ("stream", "stream_options")}
    sent["model"] = name
    if provider == "openai":
        url, headers = _endpoint(provider)
        request, dropped = to_responses_request(sent, state)
        return "responses", url.rsplit("/chat/completions", 1)[0] + "/responses", headers, request, dropped
    if provider == "anthropic":
        if "max_completion_tokens" in sent:
            sent.setdefault("max_tokens", sent.pop("max_completion_tokens"))
        return "chat", ANTHROPIC_OPENAI_URL, {"Authorization": f"Bearer {_anthropic_key()}"}, sent, []
    url, headers = _endpoint(provider)
    if provider == "openrouter":
        sent["usage"] = {"include": True}
    return "chat", url, headers, sent, []


def send(model: str, body: dict[str, Any], state: State | None = None,
         transport: httpx.BaseTransport | None = None) -> tuple[dict[str, Any], Reply]:
    """Send the request and return the chat-completions reply and its summary (``reply.state`` = reasoning to keep)."""
    kind, url, headers, request, dropped = _target(model, body, state)
    started = time.monotonic()
    if kind == "responses":
        try:
            raw = _post(url, headers, request, transport)
        except ProviderError as exc:
            if STALE_REASONING not in str(exc) or not any(i.get("type") == "reasoning" for i in request["input"]):
                raise
            raw = _post(url, headers, without_reasoning(request), transport)  # kept reasoning expired: same model, once
            dropped = [*dropped, "kept reasoning (expired)"]
        data = to_chat_completion(raw)
        reply = _summary(data, model)
        reply.state = state_from(raw.get("output") or [])
    else:
        data = _post(url, headers, request, transport)
        try:
            reply = _summary(data, model)
        except (KeyError, IndexError, TypeError, AttributeError) as exc:
            raise ProviderError(f"unexpected reply shape from {split(model)[0]}") from exc
    reply.seconds, reply.dropped = round(time.monotonic() - started, 2), dropped
    return data, reply


def _events(client: httpx.Client, url: str, headers: dict[str, str], request: dict[str, Any]) -> Iterator[dict[str, Any]]:
    """POST a streaming request and yield each JSON event; raise ProviderError for an HTTP error."""
    host = httpx.URL(url).host
    with client.stream("POST", url, headers=headers, json=request) as response:
        if response.status_code >= 400:
            response.read()
            raise http_error(response.status_code, host, response.text)
        for line in response.iter_lines():
            data = line[5:].strip() if line.startswith("data:") else ""
            if data and data != "[DONE]":
                try:
                    yield json.loads(data)
                except ValueError:
                    continue


def send_stream(model: str, body: dict[str, Any], state: State | None = None,
                transport: httpx.BaseTransport | None = None) -> Iterator[dict[str, Any] | Reply]:
    """Stream the reply as chat-completions deltas (``{"delta": ..., "finish_reason": ...}``), then one ``Reply``.

    An error before the first delta raises ``ProviderError``; after it, the stream ends with ``stop = "error"``.
    """
    kind, url, headers, request, dropped = _target(model, body, state)
    started = time.monotonic()
    reply = Reply(text="", model=model, dropped=dropped)
    started_output = False
    try:
        with _client(transport) as client:
            if kind == "responses":
                request = {**request, "stream": True}
                try:
                    events = _events(client, url, headers, request)
                    first = next(events, None)
                except ProviderError as exc:
                    if STALE_REASONING not in str(exc) or not any(i.get("type") == "reasoning" for i in request["input"]):
                        raise
                    events = _events(client, url, headers, without_reasoning(request))
                    first = next(events, None)
                    reply.dropped = [*dropped, "kept reasoning (expired)"]
                for delta in _from_responses(_chain([first] if first else [], events), reply):
                    started_output = True
                    yield delta
            else:
                request = {**request, "stream": True, "stream_options": {"include_usage": True}}
                for delta in _from_chat(_events(client, url, headers, request), reply):
                    started_output = True
                    yield delta
    except ProviderError:
        if not started_output:
            raise
        reply.stop = "error"
    except httpx.HTTPError as exc:
        if not started_output:
            raise ProviderError(f"{type(exc).__name__} calling {httpx.URL(url).host}") from exc
        reply.stop = "error"
    reply.truncated = reply.stop == "length"
    reply.seconds = round(time.monotonic() - started, 2)
    yield reply


def _chain(*iterables: Any) -> Iterator[Any]:
    for it in iterables:
        yield from it


def _from_responses(events: Iterator[dict[str, Any]], reply: Reply) -> Iterator[dict[str, Any]]:
    """Responses-API stream events as chat-completions deltas; fill ``reply`` as they arrive."""
    index: dict[int, int] = {}  # output_index -> tool_calls index
    yield {"delta": {"role": "assistant", "content": ""}}
    for event in events:
        kind = event.get("type", "")
        if kind == "response.output_item.added" and (event.get("item") or {}).get("type") == "function_call":
            item = event["item"]
            index[int(event.get("output_index", 0))] = len(index)
            call = {"id": str(item.get("call_id", "")), "type": "function",
                    "function": {"name": str(item.get("name", "")), "arguments": ""}}
            reply.tool_calls.append(call)
            yield {"delta": {"tool_calls": [{"index": len(index) - 1, **call}]}}
        elif kind == "response.function_call_arguments.delta":
            i = index.get(int(event.get("output_index", 0)))
            if i is not None:
                reply.tool_calls[i]["function"]["arguments"] += str(event.get("delta", ""))
                yield {"delta": {"tool_calls": [{"index": i, "function": {"arguments": str(event.get("delta", ""))}}]}}
        elif kind in ("response.output_text.delta", "response.refusal.delta"):
            reply.text += str(event.get("delta", ""))
            yield {"delta": {"content": str(event.get("delta", ""))}}
        elif kind in ("response.completed", "response.incomplete"):
            data = event.get("response") or {}
            usage = data.get("usage") or {}
            reply.input_tokens = int(usage.get("input_tokens", 0) or 0)
            reply.output_tokens = int(usage.get("output_tokens", 0) or 0)
            reply.served_by = str(data.get("model") or "")
            reply.state = state_from(data.get("output") or [])
            reply.stop = _finish(str(data.get("status", "")), data.get("incomplete_details"), bool(reply.tool_calls))
            yield {"delta": {}, "finish_reason": reply.stop}
        elif kind in ("response.failed", "error"):
            detail = (event.get("response") or {}).get("error") or event.get("error") or event
            raise ProviderError(f"OpenAI stream error: {str(detail)[:200]}")


def _from_chat(events: Iterator[dict[str, Any]], reply: Reply) -> Iterator[dict[str, Any]]:
    """Chat-completions stream chunks as deltas; fill ``reply`` as they arrive."""
    for event in events:
        usage = event.get("usage") or {}
        if usage:
            reply.input_tokens = int(usage.get("prompt_tokens", 0) or 0)
            reply.output_tokens = int(usage.get("completion_tokens", 0) or 0)
            if isinstance(usage.get("cost"), (int, float)):
                reply.cost = float(usage["cost"])
        if event.get("model"):
            reply.served_by = str(event["model"])
        for choice in event.get("choices") or []:
            delta = dict(choice.get("delta") or {})
            if delta.get("content"):
                reply.text += str(delta["content"])
            for call in delta.get("tool_calls") or []:
                i = int(call.get("index", 0))
                while len(reply.tool_calls) <= i:
                    reply.tool_calls.append({"id": "", "type": "function", "function": {"name": "", "arguments": ""}})
                kept = reply.tool_calls[i]
                kept["id"] = call.get("id") or kept["id"]
                fn = call.get("function") or {}
                kept["function"]["name"] = fn.get("name") or kept["function"]["name"]
                kept["function"]["arguments"] += str(fn.get("arguments") or "")
            if choice.get("finish_reason"):
                reply.stop = str(choice["finish_reason"])
            if delta or choice.get("finish_reason"):
                yield {"delta": delta, "finish_reason": choice.get("finish_reason")}
