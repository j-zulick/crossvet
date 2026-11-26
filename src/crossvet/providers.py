"""Call any model through its vendor's API with one function.

A model is named ``provider:model``. Keys come from the environment and are never logged:

    openai:gpt-...              OPENAI_API_KEY
    anthropic:claude-...        ANTHROPIC_API_KEY
    google:gemini-...           GOOGLE_API_KEY       (Google's OpenAI-compatible endpoint)
    xai:grok-...                XAI_API_KEY
    openrouter:vendor/model     OPENROUTER_API_KEY   (one key for most vendors; reports real cost)
    ollama:gemma3               no key               (OLLAMA_BASE_URL, default http://localhost:11434/v1)
    local:<name>                LOCAL_API_KEY opt.   (LOCAL_BASE_URL: any OpenAI-compatible server)

Only the vendors' APIs are used: no chat website is driven and no subscription login is used.

``passthrough`` forwards a whole OpenAI-style request (tools, tool results, temperature and the
rest) to one model and returns its reply in the chat-completions shape, so an agent that calls tools
keeps them. Anthropic models get it through Anthropic's OpenAI-compatible endpoint; OpenAI models
through OpenAI's Responses API, because OpenAI's current models refuse tools on chat completions.
"""

from __future__ import annotations

import json
import os
import time
from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Any

import httpx

OPENAI_STYLE = {
    "openai": ("https://api.openai.com/v1", "OPENAI_API_KEY"),
    "google": ("https://generativelanguage.googleapis.com/v1beta/openai", "GOOGLE_API_KEY"),
    "xai": ("https://api.x.ai/v1", "XAI_API_KEY"),
    "openrouter": ("https://openrouter.ai/api/v1", "OPENROUTER_API_KEY"),
    "ollama": ("http://localhost:11434/v1", ""),
    "local": ("", "LOCAL_API_KEY"),
}
BASE_URL_ENV = {"ollama": "OLLAMA_BASE_URL", "local": "LOCAL_BASE_URL"}
PROVIDERS = ("anthropic", *OPENAI_STYLE)
ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"
ANTHROPIC_OPENAI_URL = "https://api.anthropic.com/v1/chat/completions"  # used for requests that carry tools
ANTHROPIC_VERSION = "2023-06-01"
TIMEOUT = httpx.Timeout(120.0, connect=10.0)


def set_timeout(seconds: float) -> None:
    """Set how long one model call may take (``[limits] timeout_seconds``); connecting may take 10 s of it."""
    global TIMEOUT  # noqa: PLW0603 - one setting for every call in this process
    TIMEOUT = httpx.Timeout(float(seconds), connect=min(10.0, float(seconds)))


class ProviderError(RuntimeError):
    """A model call failed: no key, an HTTP error, or a reply that could not be read."""


class AccountError(ProviderError):
    """The provider refused the account (bad key, no credit, a spending limit, billing): retrying will not help."""


ACCOUNT_MARKERS = ("insufficient_quota", "exceeded your current quota", "insufficient credit", "credit balance",
                   "billing", "payment", "spending limit", "quota exceeded", "account is not active", "invalid api key",
                   "invalid_api_key", "incorrect api key", "invalid x-api-key")


def http_error(status: int, host: str, text: str) -> ProviderError:
    """Return the error for an HTTP failure; account refusals become :class:`AccountError` (decided in code)."""
    low = text.lower()
    if status in (401, 402) or (status in (403, 429) and any(m in low for m in ACCOUNT_MARKERS)):
        return AccountError(f"HTTP {status} from {host}: the account was refused (key, credit or billing); "
                            f"fix it with the provider: {text[:300]}")
    return ProviderError(f"HTTP {status} from {host}: {text[:300]}")


@dataclass
class Reply:
    """One model's answer."""

    text: str
    model: str
    input_tokens: int = 0
    output_tokens: int = 0
    cost: float | None = None      # USD as reported by the provider (OpenRouter); None when it reports none
    truncated: bool = False        # stopped at the output limit
    seconds: float = 0.0
    stop: str = ""
    served_by: str = ""            # the model id the provider says answered
    tool_calls: list[dict[str, Any]] = field(default_factory=list)


def split(model: str) -> tuple[str, str]:
    """Split ``provider:model``; reject a name without a known provider."""
    provider, _, name = model.partition(":")
    if provider not in PROVIDERS or not name:
        raise ProviderError(f"a model is written provider:model with a provider from {', '.join(PROVIDERS)}; got {model!r}")
    return provider, name


def key_name(provider: str) -> str:
    """Return the environment variable this provider needs ("" when it needs none)."""
    if provider == "anthropic":
        return "ANTHROPIC_API_KEY"
    if provider == "local":
        return "LOCAL_BASE_URL"
    return OPENAI_STYLE[provider][1]


def available(provider: str) -> bool:
    """Whether this provider can be called with the environment as it is (Ollama needs no key)."""
    name = key_name(provider)
    return True if not name else bool(os.environ.get(name))


def _client(transport: httpx.BaseTransport | None) -> httpx.Client:
    return httpx.Client(timeout=TIMEOUT, transport=transport)


def _post(url: str, headers: dict[str, str], body: dict[str, Any], transport: httpx.BaseTransport | None) -> dict[str, Any]:
    host = httpx.URL(url).host
    try:
        with _client(transport) as client:
            response = client.post(url, headers=headers, json=body)
    except httpx.HTTPError as exc:
        raise ProviderError(f"{type(exc).__name__} calling {host}") from exc
    if response.status_code >= 400:
        raise http_error(response.status_code, host, response.text)
    try:
        return response.json()
    except ValueError as exc:
        raise ProviderError(f"{host} did not return JSON") from exc


def _anthropic_key() -> str:
    key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not key:
        raise ProviderError("ANTHROPIC_API_KEY is not set")
    return key


def _endpoint(provider: str) -> tuple[str, dict[str, str]]:
    """Return the chat-completions URL and headers for an OpenAI-style provider."""
    base, key_env = OPENAI_STYLE[provider]
    base = os.environ.get(BASE_URL_ENV.get(provider, ""), "") or base
    if not base:
        raise ProviderError("LOCAL_BASE_URL is not set")
    key = os.environ.get(key_env, "") if key_env else ""
    if key_env and not key and provider != "local":
        raise ProviderError(f"{key_env} is not set")
    headers = {"Authorization": f"Bearer {key}"} if key else {}
    if provider == "openrouter":  # the app name OpenRouter shows in its activity log
        headers["X-Title"] = "Crossvet"
        headers["HTTP-Referer"] = "https://github.com/j-zulick/crossvet"
    return f"{base.rstrip('/')}/chat/completions", headers


def limit_field(provider: str) -> str:
    """Return the request field for the output limit (OpenAI's current models take only ``max_completion_tokens``)."""
    return "max_completion_tokens" if provider == "openai" else "max_tokens"


def call(model: str, messages: list[dict[str, Any]], max_tokens: int = 4000,
         transport: httpx.BaseTransport | None = None) -> Reply:
    """Send ``messages`` (role/content dicts; system messages are allowed) to ``model`` and return the whole answer."""
    reply: Reply | None = None
    for item in stream(model, messages, max_tokens, transport):
        if isinstance(item, Reply):
            reply = item
    assert reply is not None  # stream always ends with a Reply  # noqa: S101
    return reply


def stream(model: str, messages: list[dict[str, Any]], max_tokens: int = 4000,
           transport: httpx.BaseTransport | None = None) -> Iterator[str | Reply]:
    """Stream ``model``'s answer: yield each piece of text as it arrives, then one finished ``Reply``.

    An error before the first piece raises ``ProviderError``; an error after it ends the stream
    with the text so far and ``stop = "error"``, so the caller can record what happened.
    """
    provider, name = split(model)
    started = time.monotonic()
    if provider == "anthropic":
        system, turns = anthropic_turns(messages)
        body: dict[str, Any] = {"model": name, "max_tokens": max_tokens, "stream": True, "messages": turns}
        if system:
            body["system"] = system
        url = ANTHROPIC_URL
        headers = {"x-api-key": _anthropic_key(), "anthropic-version": ANTHROPIC_VERSION}
        parse = _anthropic_event
    else:
        url, headers = _endpoint(provider)
        body = {"model": name, "messages": messages, limit_field(provider): max_tokens, "stream": True,
                "stream_options": {"include_usage": True}}
        if provider == "openrouter":
            body["usage"] = {"include": True}  # ask for the real cost of the call
        parse = _openai_event
    host = httpx.URL(url).host
    reply = Reply(text="", model=model)
    pieces: list[str] = []
    try:
        with _client(transport) as client, client.stream("POST", url, headers=headers, json=body) as response:
            if response.status_code >= 400:
                response.read()
                raise http_error(response.status_code, host, response.text)
            if "text/event-stream" not in response.headers.get("content-type", ""):
                response.read()  # a server that ignores "stream" and answers in one piece
                try:
                    whole = _whole_reply(provider, response.json())
                except ValueError as exc:
                    raise ProviderError(f"{host} did not return JSON or a stream") from exc
                whole.model, whole.seconds = model, round(time.monotonic() - started, 2)
                if whole.text:
                    yield whole.text
                yield whole
                return
            for line in response.iter_lines():
                data = line[5:].strip() if line.startswith("data:") else ""
                if not data or data == "[DONE]":
                    continue
                try:
                    event = json.loads(data)
                except ValueError:
                    continue
                piece = parse(event, reply)
                if piece:
                    pieces.append(piece)
                    yield piece
    except ProviderError:
        if not pieces:
            raise
        reply.stop = "error"
    except httpx.HTTPError as exc:
        if not pieces:
            raise ProviderError(f"{type(exc).__name__} calling {host}") from exc
        reply.stop = "error"
    reply.text = "".join(pieces)
    reply.truncated = reply.truncated or reply.stop in ("length", "max_tokens")
    reply.seconds = round(time.monotonic() - started, 2)
    yield reply


def passthrough(model: str, body: dict[str, Any], transport: httpx.BaseTransport | None = None) -> tuple[dict[str, Any], Reply]:
    """Send a full OpenAI-style request to ``model``; return the raw reply and a ``Reply`` summary.

    ``stream`` is turned off upstream (the server re-streams the finished reply).
    """
    provider, name = split(model)
    sent = {k: v for k, v in body.items() if k not in ("stream", "stream_options")}
    sent["model"] = name
    if provider == "openai":  # OpenAI's current models take tools only through the Responses API
        url, headers = _endpoint(provider)
        started = time.monotonic()
        data = to_chat_completion(_post(url.rsplit("/chat/completions", 1)[0] + "/responses", headers,
                                        to_responses_request(sent), transport))
        reply, message = _openai_reply(data, provider)
        reply.model, reply.seconds = model, round(time.monotonic() - started, 2)
        reply.tool_calls = list(message.get("tool_calls") or [])
        return data, reply
    if provider == "anthropic":
        url, headers = ANTHROPIC_OPENAI_URL, {"Authorization": f"Bearer {_anthropic_key()}"}
        if "max_completion_tokens" in sent:
            sent.setdefault("max_tokens", sent.pop("max_completion_tokens"))
    else:
        url, headers = _endpoint(provider)
        if provider == "openrouter":
            sent["usage"] = {"include": True}
    started = time.monotonic()
    data = _post(url, headers, sent, transport)
    reply, message = _openai_reply(data, provider)
    reply.model = model
    reply.seconds = round(time.monotonic() - started, 2)
    reply.tool_calls = list(message.get("tool_calls") or [])
    return data, reply


def _responses_content(content: Any, role: str) -> Any:
    """Turn chat-style content (a string or parts) into Responses-API content."""
    if not isinstance(content, list):
        return text_of(content)
    kind = "output_text" if role == "assistant" else "input_text"
    parts = []
    for part in content:
        if not isinstance(part, dict):
            continue
        if part.get("type") in ("text", "input_text", "output_text"):
            parts.append({"type": kind, "text": str(part.get("text", ""))})
        elif part.get("type") == "image_url":
            parts.append({"type": "input_image", "image_url": str((part.get("image_url") or {}).get("url", ""))})
        else:
            raise ProviderError(f"Crossvet sends text and images to OpenAI with tools; a {part.get('type')!r} part is not supported")
    return parts


def to_responses_request(body: dict[str, Any]) -> dict[str, Any]:
    """Turn a chat-completions request (with tools) into an OpenAI Responses-API request."""
    items: list[dict[str, Any]] = []
    for m in body.get("messages") or []:
        role = m.get("role")
        if role == "tool":
            items.append({"type": "function_call_output", "call_id": str(m.get("tool_call_id", "")),
                          "output": text_of(m.get("content"))})
            continue
        if role == "function":
            raise ProviderError("the old 'function' role is not supported; send tool results with role 'tool'")
        content = _responses_content(m.get("content"), str(role))
        if content:
            items.append({"role": role, "content": content})
        for call in m.get("tool_calls") or []:
            fn = call.get("function") or {}
            items.append({"type": "function_call", "call_id": str(call.get("id", "")), "name": str(fn.get("name", "")),
                          "arguments": str(fn.get("arguments") or "{}")})
    out: dict[str, Any] = {"model": body["model"], "input": items, "store": False}
    tools = []
    for tool in body.get("tools") or []:
        fn = tool.get("function") or {}
        if tool.get("type") == "function" and fn.get("name"):
            tools.append({"type": "function", "name": fn["name"], "description": fn.get("description", ""),
                          "parameters": fn.get("parameters") or {"type": "object", "properties": {}},
                          "strict": bool(fn.get("strict", False))})
    if tools:
        out["tools"] = tools
    choice = body.get("tool_choice")
    if isinstance(choice, dict):
        out["tool_choice"] = {"type": "function", "name": (choice.get("function") or {}).get("name", "")}
    elif choice:
        out["tool_choice"] = choice
    limit = body.get("max_completion_tokens", body.get("max_tokens"))
    if limit:
        out["max_output_tokens"] = int(limit)
    if body.get("reasoning_effort"):
        out["reasoning"] = {"effort": body["reasoning_effort"]}
    for key in ("temperature", "top_p", "parallel_tool_calls", "user"):
        if key in body:
            out[key] = body[key]
    fmt = body.get("response_format") or {}
    if fmt.get("type") == "json_object":
        out["text"] = {"format": {"type": "json_object"}}
    elif fmt.get("type") == "json_schema":
        out["text"] = {"format": {"type": "json_schema", **(fmt.get("json_schema") or {})}}
    return out


def to_chat_completion(data: dict[str, Any]) -> dict[str, Any]:
    """Turn an OpenAI Responses-API reply into a chat-completions reply."""
    text: list[str] = []
    calls: list[dict[str, Any]] = []
    for item in data.get("output") or []:
        if item.get("type") == "message":
            text += [str(c.get("text", "")) for c in item.get("content") or [] if c.get("type") == "output_text"]
        elif item.get("type") == "function_call":
            calls.append({"id": str(item.get("call_id", "")), "type": "function",
                          "function": {"name": str(item.get("name", "")), "arguments": str(item.get("arguments") or "{}")}})
    if "output" not in data:
        raise ProviderError("unexpected reply shape from openai (responses)")
    incomplete = (data.get("incomplete_details") or {}).get("reason") == "max_output_tokens"
    finish = "tool_calls" if calls else "length" if incomplete else "stop"
    message: dict[str, Any] = {"role": "assistant", "content": "".join(text) or None}
    if calls:
        message["tool_calls"] = calls
    usage = data.get("usage") or {}
    return {"id": str(data.get("id", "")), "object": "chat.completion", "created": int(data.get("created_at") or time.time()),
            "model": str(data.get("model") or ""), "choices": [{"index": 0, "message": message, "finish_reason": finish}],
            "usage": {"prompt_tokens": int(usage.get("input_tokens", 0) or 0),
                      "completion_tokens": int(usage.get("output_tokens", 0) or 0),
                      "total_tokens": int(usage.get("total_tokens", 0) or 0)}}


def _content(message: dict[str, Any]) -> str:
    text = message.get("content") or ""
    if isinstance(text, list):  # some servers return content parts
        text = "".join(part.get("text", "") for part in text if isinstance(part, dict))
    return str(text)


def _openai_reply(data: dict[str, Any], provider: str) -> tuple[Reply, dict[str, Any]]:
    try:
        choice = data["choices"][0]
        message = choice.get("message") or {}
    except (KeyError, IndexError, TypeError, AttributeError) as exc:
        raise ProviderError(f"unexpected reply shape from {provider}") from exc
    usage = data.get("usage") or {}
    stop = str(choice.get("finish_reason") or "")
    cost = usage.get("cost")
    reply = Reply(text=_content(message), model="", input_tokens=int(usage.get("prompt_tokens", 0) or 0),
                  output_tokens=int(usage.get("completion_tokens", 0) or 0),
                  cost=float(cost) if isinstance(cost, (int, float)) else None,
                  truncated=stop == "length", stop=stop, served_by=str(data.get("model") or ""))
    return reply, message


def _anthropic_usage(usage: dict[str, Any]) -> int:
    return sum(int(usage.get(k, 0) or 0) for k in ("input_tokens", "cache_read_input_tokens", "cache_creation_input_tokens"))


def _whole_reply(provider: str, data: dict[str, Any]) -> Reply:
    """Read a complete (not streamed) reply from either API shape."""
    if provider != "anthropic":
        return _openai_reply(data, provider)[0]
    try:
        text = "".join(block.get("text", "") for block in data["content"] if block.get("type") == "text")
    except (KeyError, TypeError) as exc:
        raise ProviderError("unexpected reply shape from anthropic") from exc
    usage = data.get("usage") or {}
    stop = str(data.get("stop_reason") or "")
    return Reply(text=text, model="", input_tokens=_anthropic_usage(usage), output_tokens=int(usage.get("output_tokens", 0) or 0),
                 truncated=stop == "max_tokens", stop=stop, served_by=str(data.get("model") or ""))


def _openai_event(event: dict[str, Any], reply: Reply) -> str:
    """Read one OpenAI-style stream chunk into ``reply``; return its text."""
    usage = event.get("usage") or {}
    if usage:
        reply.input_tokens = int(usage.get("prompt_tokens", 0) or 0)
        reply.output_tokens = int(usage.get("completion_tokens", 0) or 0)
        cost = usage.get("cost")
        if isinstance(cost, (int, float)):
            reply.cost = float(cost)
    if event.get("model"):
        reply.served_by = str(event["model"])
    choices = event.get("choices") or []
    if not choices:
        return ""
    choice = choices[0] or {}
    if choice.get("finish_reason"):
        reply.stop = str(choice["finish_reason"])
    return _content(choice.get("delta") or {})


def _anthropic_event(event: dict[str, Any], reply: Reply) -> str:
    """Read one Anthropic stream event into ``reply``; return its text."""
    kind = event.get("type")
    if kind == "message_start":
        message = event.get("message") or {}
        reply.input_tokens = _anthropic_usage(message.get("usage") or {})
        reply.served_by = str(message.get("model") or "")
    elif kind == "content_block_delta":
        delta = event.get("delta") or {}
        if delta.get("type") == "text_delta":
            return str(delta.get("text", ""))
    elif kind == "message_delta":
        reply.stop = str((event.get("delta") or {}).get("stop_reason") or reply.stop)
        reply.output_tokens = int((event.get("usage") or {}).get("output_tokens", 0) or reply.output_tokens)
    elif kind == "error":
        raise ProviderError("anthropic: " + str((event.get("error") or {}).get("message", "stream error"))[:200])
    return ""


def text_of(content: Any) -> str:
    """Return the text of a message's content, whether a string or a list of parts."""
    if isinstance(content, list):
        return "\n".join(str(p.get("text", "")) for p in content if isinstance(p, dict) and p.get("type") in ("text", "input_text"))
    return str(content or "")


def _anthropic_part(part: dict[str, Any]) -> dict[str, Any]:
    """Turn one OpenAI-style content part (text or image) into Anthropic's shape."""
    kind = part.get("type")
    if kind in ("text", "input_text"):
        return {"type": "text", "text": str(part.get("text", ""))}
    if kind == "image_url":
        url = str((part.get("image_url") or {}).get("url", ""))
        if url.startswith("data:") and ";base64," in url:
            media, _, data = url[5:].partition(";base64,")
            return {"type": "image", "source": {"type": "base64", "media_type": media, "data": data}}
        if url.startswith("https://"):
            return {"type": "image", "source": {"type": "url", "url": url}}
        raise ProviderError("an image must be a data: URL or an https:// URL")
    raise ProviderError(f"Crossvet sends text and images to Anthropic models; a {kind!r} part is not supported")


def anthropic_turns(messages: list[dict[str, Any]]) -> tuple[str, list[dict[str, Any]]]:
    """Split ``messages`` into Anthropic's system text and turns."""
    system = "\n\n".join(text_of(m["content"]) for m in messages if m["role"] == "system")
    turns = []
    for m in messages:
        if m["role"] == "system":
            continue
        content = m["content"]
        if isinstance(content, list):
            content = [_anthropic_part(p) for p in content if isinstance(p, dict)]
        turns.append({"role": m["role"], "content": content})
    return system, turns
