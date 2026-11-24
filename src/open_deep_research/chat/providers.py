"""Call any model through its vendor's API with one function.

A model is named ``provider:model``. Keys come from the environment and are never logged:

    openrouter:openai/gpt-...   OPENROUTER_API_KEY   (one key for most vendors; reports real cost)
    openai:gpt-...              OPENAI_API_KEY
    anthropic:claude-...        ANTHROPIC_API_KEY
    google:gemini-...           GOOGLE_API_KEY       (Google's OpenAI-compatible endpoint)
    xai:grok-...                XAI_API_KEY
    ollama:gemma3               no key               (OLLAMA_BASE_URL, default http://localhost:11434/v1)
    local:<name>                LOCAL_API_KEY opt.   (LOCAL_BASE_URL: any OpenAI-compatible server)

No chat website is driven and no subscription login is used: only the vendors' APIs.

``passthrough`` forwards a whole OpenAI-style request (tools, tool results, temperature and
the rest) to one model and returns its reply unchanged, so an agent that calls tools can use
the chat endpoint without losing them. It works for every provider except ``anthropic``
(use ``openrouter:anthropic/...`` for Anthropic models there).
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from typing import Any

import httpx

OPENAI_STYLE = {
    "openrouter": ("https://openrouter.ai/api/v1", "OPENROUTER_API_KEY"),
    "openai": ("https://api.openai.com/v1", "OPENAI_API_KEY"),
    "google": ("https://generativelanguage.googleapis.com/v1beta/openai", "GOOGLE_API_KEY"),
    "xai": ("https://api.x.ai/v1", "XAI_API_KEY"),
    "ollama": ("http://localhost:11434/v1", ""),
    "local": ("", "LOCAL_API_KEY"),
}
BASE_URL_ENV = {"ollama": "OLLAMA_BASE_URL", "local": "LOCAL_BASE_URL"}
PROVIDERS = (*OPENAI_STYLE, "anthropic")
ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"
TIMEOUT = httpx.Timeout(120.0, connect=10.0)


class ProviderError(RuntimeError):
    """A model call failed: no key, an HTTP error, or a reply that could not be read."""


@dataclass
class Reply:
    """One model's answer."""

    text: str
    model: str
    input_tokens: int = 0
    output_tokens: int = 0
    cost: float | None = None      # USD as reported by the provider; None when it reports none
    truncated: bool = False        # stopped at the output limit
    seconds: float = 0.0
    raw_stop: str = ""
    extra: dict[str, Any] = field(default_factory=dict)


def split(model: str) -> tuple[str, str]:
    """Split ``provider:model``; reject a name without a known provider."""
    provider, _, name = model.partition(":")
    if provider not in PROVIDERS or not name:
        raise ProviderError(f"model must be written provider:model with a provider from {', '.join(PROVIDERS)}; got {model!r}")
    return provider, name


def vendor_of(model: str) -> str:
    """Return the company that made a model: for OpenRouter the part before the slash, else the provider."""
    provider, name = split(model)
    if provider == "openrouter" and "/" in name:
        return name.split("/", 1)[0].lower()
    return {"xai": "x-ai"}.get(provider, provider)


def key_name(provider: str) -> str:
    """Return the environment variable this provider needs ("" when it needs none)."""
    if provider == "anthropic":
        return "ANTHROPIC_API_KEY"
    if provider == "local":
        return "LOCAL_BASE_URL"
    return OPENAI_STYLE[provider][1]


def available(provider: str) -> bool:
    """Whether this provider can be called with the environment as it is."""
    if provider == "anthropic":
        return bool(os.environ.get("ANTHROPIC_API_KEY"))
    if provider == "ollama":
        return True
    if provider == "local":
        return bool(os.environ.get("LOCAL_BASE_URL"))
    return bool(os.environ.get(OPENAI_STYLE[provider][1]))


def _client(transport: httpx.BaseTransport | None) -> httpx.Client:
    return httpx.Client(timeout=TIMEOUT, transport=transport)


def _post(url: str, headers: dict[str, str], body: dict[str, Any], transport: httpx.BaseTransport | None) -> dict[str, Any]:
    try:
        with _client(transport) as client:
            response = client.post(url, headers=headers, json=body)
    except httpx.HTTPError as exc:
        raise ProviderError(f"{type(exc).__name__} calling {httpx.URL(url).host}") from exc
    if response.status_code >= 400:
        raise ProviderError(f"HTTP {response.status_code} from {httpx.URL(url).host}: {response.text[:300]}")
    try:
        return response.json()
    except ValueError as exc:
        raise ProviderError(f"{httpx.URL(url).host} did not return JSON") from exc


def call(model: str, messages: list[dict[str, str]], max_tokens: int = 4000,
         transport: httpx.BaseTransport | None = None) -> Reply:
    """Send ``messages`` (role/content dicts; a leading system message is allowed) to ``model``."""
    provider, name = split(model)
    started = time.monotonic()
    reply = _anthropic(name, messages, max_tokens, transport) if provider == "anthropic" \
        else _openai_style(provider, name, messages, max_tokens, transport)
    reply.model = model
    reply.seconds = round(time.monotonic() - started, 2)
    return reply


def _headers(provider: str, key: str) -> dict[str, str]:
    headers = {"Authorization": f"Bearer {key}"} if key else {}
    if provider == "openrouter":  # attribution OpenRouter shows in its activity log
        headers["X-Title"] = os.environ.get("OPENROUTER_APP_TITLE", "") or "Crossvet chat"
        headers["HTTP-Referer"] = os.environ.get("OPENROUTER_APP_URL", "") or "https://github.com/j-zulick/crossvet"
    return headers


def _endpoint(provider: str) -> tuple[str, dict[str, str]]:
    """Return the chat-completions URL and headers for an OpenAI-style provider."""
    base, key_env = OPENAI_STYLE[provider]
    base = os.environ.get(BASE_URL_ENV.get(provider, ""), "") or base
    if not base:
        raise ProviderError("LOCAL_BASE_URL is not set")
    key = os.environ.get(key_env, "") if key_env else ""
    if key_env and not key and provider != "local":
        raise ProviderError(f"{key_env} is not set")
    return f"{base.rstrip('/')}/chat/completions", _headers(provider, key)


def _content(message: dict[str, Any]) -> str:
    text = message.get("content") or ""
    if isinstance(text, list):  # some servers return content parts
        text = "".join(part.get("text", "") for part in text if isinstance(part, dict))
    return str(text)


def _reply(data: dict[str, Any], provider: str) -> tuple[Reply, dict[str, Any]]:
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
                  truncated=stop == "length", raw_stop=stop, extra={"served_by": str(data.get("model") or "")})
    return reply, message


def passthrough(model: str, body: dict[str, Any], transport: httpx.BaseTransport | None = None) -> tuple[dict[str, Any], Reply]:
    """Send a full OpenAI-style request to ``model``; return the raw reply and a ``Reply`` summary.

    ``stream`` is turned off upstream (the server re-streams the finished reply).
    """
    provider, name = split(model)
    if provider == "anthropic":
        raise ProviderError("tool calls are passed through only to OpenAI-style providers; use openrouter:anthropic/<model>")
    url, headers = _endpoint(provider)
    sent = {k: v for k, v in body.items() if k not in ("stream", "stream_options")}
    sent["model"] = name
    if provider == "openrouter":
        sent["usage"] = {"include": True}
    started = time.monotonic()
    data = _post(url, headers, sent, transport)
    reply, message = _reply(data, provider)
    reply.model = model
    reply.seconds = round(time.monotonic() - started, 2)
    reply.extra["tool_calls"] = message.get("tool_calls") or []
    return data, reply


def _openai_style(provider: str, name: str, messages: list[dict[str, str]], max_tokens: int,
                  transport: httpx.BaseTransport | None) -> Reply:
    url, headers = _endpoint(provider)
    body: dict[str, Any] = {"model": name, "messages": messages, "max_tokens": max_tokens}
    if provider == "openrouter":
        body["usage"] = {"include": True}  # ask for the real cost of the call
    return _reply(_post(url, headers, body, transport), provider)[0]


def _anthropic(name: str, messages: list[dict[str, str]], max_tokens: int,
               transport: httpx.BaseTransport | None) -> Reply:
    key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not key:
        raise ProviderError("ANTHROPIC_API_KEY is not set")
    system = "\n\n".join(m["content"] for m in messages if m["role"] == "system")
    turns = [m for m in messages if m["role"] != "system"]
    body: dict[str, Any] = {"model": name, "max_tokens": max_tokens, "messages": turns}
    if system:
        body["system"] = system
    data = _post(ANTHROPIC_URL, {"x-api-key": key, "anthropic-version": "2023-06-01"}, body, transport)
    try:
        text = "".join(block.get("text", "") for block in data["content"] if block.get("type") == "text")
    except (KeyError, TypeError) as exc:
        raise ProviderError("unexpected reply shape from anthropic") from exc
    usage = data.get("usage") or {}
    stop = str(data.get("stop_reason") or "")
    return Reply(text=text, model="", input_tokens=int(usage.get("input_tokens", 0) or 0),
                 output_tokens=int(usage.get("output_tokens", 0) or 0),
                 truncated=stop == "max_tokens", raw_stop=stop)
