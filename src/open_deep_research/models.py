"""One way to build a chat model for any role, from a ``provider:model`` string.

Every stage (orchestration, research, summarization, compression, report writing) and
every review role (reviewer, critic, reviser, challenger, blind pass) is built here, so a
model that works in one role works in all of them:

- ``openrouter:<maker>/<model>``: OpenRouter, through the official ``langchain-openrouter``
  integration (real per-call cost in ``response_metadata["cost"]``, provider routing,
  attribution as Crossvet);
- ``local:<model>``: any OpenAI-compatible server (llama.cpp, LM Studio, MLX, vLLM) at
  ``LOCAL_LLM_BASE_URL``;
- anything else (``openai:``, ``anthropic:``, ``google_genai:``, ``ollama:``, ...): LangChain's
  ``init_chat_model``.

It also answers, before a run starts, whether a model can do what a role needs (tool calls,
structured output), and how to ask it for structured output.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any

from langchain.chat_models import init_chat_model
from langchain_core.language_models import BaseChatModel

REPO_URL = "https://github.com/j-zulick/crossvet"

# Providers that LangChain's configurable model cannot build with only model/max_tokens/api_key.
ROUTED_PROVIDERS = ("openrouter", "local")

KEY_ENV = {
    "openai": "OPENAI_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
    "google_genai": "GOOGLE_API_KEY",
    "google": "GOOGLE_API_KEY",
    "openrouter": "OPENROUTER_API_KEY",
    "deepseek": "DEEPSEEK_API_KEY",
    "groq": "GROQ_API_KEY",
}

# Roles and what each needs from a model. Tool calls: the model must call tools itself.
# Structured: the role parses typed output (with_structured_output).
ROLE_NEEDS: dict[str, set[str]] = {
    "supervisor": {"tool_calling"},
    "researcher": {"tool_calling"},
    "summarization": {"structured"},
    "compression": set(),
    "final_report": set(),
    "reviewer": {"structured"},
    "critic": {"structured"},
    "reviser": set(),
}

CAPABILITY_CACHE = Path(os.getenv("CROSSVET_CACHE_DIR", Path.home() / ".cache" / "crossvet")) / "openrouter-models.json"
CACHE_MAX_AGE = 7 * 24 * 3600


def provider_of(model: str) -> str:
    """``openrouter:x-ai/grok-4`` -> ``openrouter``; a bare name -> ``""``."""
    provider, sep, _ = (model or "").strip().partition(":")
    return provider.lower() if sep else ""


def model_id(model: str) -> str:
    """Return the part after the provider: ``openrouter:x-ai/grok-4`` -> ``x-ai/grok-4``."""
    return (model or "").strip().partition(":")[2] or (model or "").strip()


def maker_of(model: str) -> str:
    """Who made the model (OpenRouter ids carry the maker before the slash)."""
    provider = provider_of(model)
    if provider == "openrouter":
        return model_id(model).split("/", 1)[0].lower()
    return provider


def is_routed(model: str) -> bool:
    """Tell whether the model needs its own client (not LangChain's configurable model)."""
    return provider_of(model) in ROUTED_PROVIDERS


def api_key_for(model: str, config: dict | None = None) -> str | None:
    """Return the API key for a model: from the run config when GET_API_KEYS_FROM_CONFIG=true, else env."""
    env = KEY_ENV.get(provider_of(model))
    if not env:
        return None
    if os.getenv("GET_API_KEYS_FROM_CONFIG", "false").lower() == "true":
        return ((config or {}).get("configurable", {}).get("apiKeys") or {}).get(env)
    return os.getenv(env) or None


def openrouter_preferences() -> dict[str, Any]:
    """OpenRouter provider routing from the environment (empty means OpenRouter's defaults).

    OPENROUTER_PROVIDER_ORDER (comma-separated hosts to try first), OPENROUTER_ALLOW_FALLBACKS
    (false = only those hosts) and OPENROUTER_DATA_COLLECTION (deny = only hosts that do not
    store or train on prompts). These choose who *hosts* a model; the model, and so its
    vendor on the panel, stays the one you named.
    """
    prefs: dict[str, Any] = {}
    order = [h.strip() for h in os.getenv("OPENROUTER_PROVIDER_ORDER", "").split(",") if h.strip()]
    if order:
        prefs["order"] = order
    fallbacks = os.getenv("OPENROUTER_ALLOW_FALLBACKS", "").strip().lower()
    if fallbacks in ("true", "false"):
        prefs["allow_fallbacks"] = fallbacks == "true"
    collection = os.getenv("OPENROUTER_DATA_COLLECTION", "").strip().lower()
    if collection in ("allow", "deny"):
        prefs["data_collection"] = collection
    return prefs


def build_chat_model(model: str, max_tokens: int | None = None, config: dict | None = None,
                     tags: list[str] | None = None) -> BaseChatModel:
    """Create a chat model for any role from a ``provider:model`` string."""
    provider = provider_of(model)
    extra: dict[str, Any] = {"tags": tags} if tags else {}
    if provider == "local":
        from langchain_openai import ChatOpenAI

        return ChatOpenAI(
            model=model_id(model),
            base_url=os.getenv("LOCAL_LLM_BASE_URL", "http://localhost:8080/v1"),
            api_key=os.getenv("LOCAL_LLM_API_KEY", "not-needed"),
            max_tokens=max_tokens,
            **extra,
        )
    if provider == "openrouter":
        from langchain_openrouter import ChatOpenRouter

        kwargs: dict[str, Any] = {
            "model": model_id(model),
            "max_tokens": max_tokens,
            "app_title": os.getenv("OPENROUTER_APP_TITLE", "Crossvet"),
            "app_url": os.getenv("OPENROUTER_APP_URL", REPO_URL),
            **extra,
        }
        key = api_key_for(model, config)
        if key:  # passing None would override the integration's own env lookup
            kwargs["api_key"] = key
        prefs = openrouter_preferences()
        if prefs:
            kwargs["openrouter_provider"] = prefs
        return ChatOpenRouter(**kwargs)
    return init_chat_model(model=model, max_tokens=max_tokens, api_key=api_key_for(model, config), **extra)


###################
# Capabilities
###################
def _load_cache() -> dict[str, Any]:
    try:
        data = json.loads(CAPABILITY_CACHE.read_text())
        if time.time() - float(data.get("fetched_at", 0)) <= CACHE_MAX_AGE:
            return data.get("models", {})
    except (OSError, ValueError, TypeError):
        pass
    return {}


def save_openrouter_catalog(models: list[dict[str, Any]]) -> None:
    """Keep what OpenRouter's /models says each model supports (written by crossvet-setup)."""
    slim = {}
    for m in models:
        if not isinstance(m, dict) or not m.get("id"):
            continue
        listed = m.get("supported_parameters")
        params = set(listed or [])
        pricing = m.get("pricing") or {}
        slim[m["id"]] = {  # no supported_parameters list at all = unknown, not "unsupported"
            "tool_calling": ("tools" in params) if listed is not None else None,
            "structured_output": ("structured_outputs" in params or "response_format" in params) if listed is not None else None,
            "context_length": m.get("context_length"),
            "prompt_price": _float(pricing.get("prompt")),
            "completion_price": _float(pricing.get("completion")),
        }
    try:
        CAPABILITY_CACHE.parent.mkdir(parents=True, exist_ok=True)
        CAPABILITY_CACHE.write_text(json.dumps({"fetched_at": time.time(), "models": slim}))
    except OSError:
        pass


def _float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def capabilities(model: str) -> dict[str, Any]:
    """Report what a model supports, as far as can be known without calling it.

    Sources, best first: OpenRouter's live catalog (cached by crossvet-setup), then the model
    profile shipped with the LangChain integration. ``None`` means unknown.
    """
    caps: dict[str, Any] = {"tool_calling": None, "structured_output": None, "source": "unknown"}
    if provider_of(model) == "openrouter":
        live = _load_cache().get(model_id(model))
        if live:
            return {**caps, **live, "source": "openrouter-catalog"}
        try:
            from langchain_openrouter.chat_models import _get_default_model_profile

            profile = _get_default_model_profile(model_id(model))
        except Exception:  # pragma: no cover - integration internals moved
            profile = {}
        if profile:
            return {**caps, "tool_calling": profile.get("tool_calling"),
                    "structured_output": profile.get("structured_output"), "source": "langchain-profile"}
    return caps


OPENROUTER_MAKER = {"openai": "openai", "anthropic": "anthropic", "google_genai": "google", "google_vertexai": "google",
                    "google": "google", "xai": "x-ai", "deepseek": "deepseek", "mistralai": "mistralai"}


def openrouter_equivalent(model: str) -> str | None:
    """Return the OpenRouter id of a direct-provider model, if the catalog lists it.

    ``anthropic:claude-sonnet-5-5`` -> ``anthropic/claude-sonnet-5.5``; used for price estimates.
    """
    import re

    maker = OPENROUTER_MAKER.get(provider_of(model))
    if not maker:
        return None
    catalog = _load_cache()
    name = model_id(model)
    dotted = re.sub(r"(?<=\d)-(?=\d)", ".", name)  # claude-sonnet-5-5 -> claude-sonnet-5.5
    for candidate in (f"{maker}/{name}", f"{maker}/{dotted}"):
        if candidate in catalog:
            return candidate
    return None


def unmet_needs(model: str, role: str) -> list[str]:
    """Needs of ``role`` that ``model`` is known NOT to meet (unknown counts as met)."""
    caps = capabilities(model)
    missing = []
    for need in ROLE_NEEDS.get(role, set()):
        if need == "tool_calling" and caps["tool_calling"] is False:
            missing.append("tool calls")
        if need == "structured" and caps["tool_calling"] is False and caps["structured_output"] is False:
            missing.append("structured output")
    return missing


def structured_output_kwargs(model: str) -> dict:
    """Arguments for ``with_structured_output`` that suit the model.

    - Claude (directly or through OpenRouter) rejects forced tool calls: native JSON schema.
    - OpenRouter models: JSON schema when the model supports structured outputs, else a forced
      tool call, which works on any model with tools (OpenRouter's own recommendation).
    - Others keep LangChain's defaults.
    """
    lowered = (model or "").lower()
    provider = provider_of(model)
    if provider == "anthropic" or lowered.startswith("claude"):
        return {"method": "json_schema"}
    if provider == "openrouter":
        if maker_of(model) == "anthropic" or capabilities(model)["structured_output"]:
            return {"method": "json_schema"}
        return {"method": "function_calling"}
    return {}


def context_limit(model: str) -> int | None:
    """Return the model's input token limit from OpenRouter's catalog or LangChain's model profiles."""
    if provider_of(model) == "openrouter":
        live = _load_cache().get(model_id(model)) or {}
        if live.get("context_length"):
            return int(live["context_length"])
    if provider_of(model) in ("local", "ollama", ""):
        return None
    try:
        profile = build_chat_model(model, 16, {"configurable": {}}).profile or {}
    except Exception:  # missing key, package or unknown model: no limit known
        return None
    value = profile.get("max_input_tokens")
    return int(value) if value else None


def message_text(message: Any) -> str:
    """Return a reply's text, without thinking or reasoning blocks.

    Claude (with extended thinking) and OpenAI's Responses API return content as a list of
    blocks; ``str(message.content)`` would put the raw blocks, signatures and all, into a report.
    """
    text = getattr(message, "text", None)
    if isinstance(text, str):
        return text
    content = getattr(message, "content", message)
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(b.get("text", "") if isinstance(b, dict) and b.get("type") == "text" else (b if isinstance(b, str) else "")
                       for b in content)
    return str(content or "")


def was_truncated(message: Any) -> bool:
    """Tell whether a reply stopped at its output limit (any provider's way of saying so).

    With extended thinking, reasoning tokens share the output budget, so a long report can be
    cut off mid-sentence even when the limit looks generous.
    """
    meta = getattr(message, "response_metadata", None) or {}
    reasons = {str(meta.get(k) or "").lower() for k in ("stop_reason", "finish_reason")}
    if reasons & {"max_tokens", "length", "max_output_tokens"}:
        return True
    incomplete = meta.get("incomplete_details") or {}
    return isinstance(incomplete, dict) and incomplete.get("reason") == "max_output_tokens"


###################
# Cost
###################
def cost_of(message: Any) -> float | None:
    """Real cost in USD reported with a response (OpenRouter returns it on every call)."""
    meta = getattr(message, "response_metadata", None) or {}
    for value in (meta.get("cost"), (meta.get("token_usage") or {}).get("cost")):
        if isinstance(value, (int, float)):
            return float(value)
    return None
