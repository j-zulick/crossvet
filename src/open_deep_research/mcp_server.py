"""MCP server exposing Crossvet's model tools to any MCP client.

Tools:
    ask_model       Ask one model (cloud, OpenRouter, Ollama or local) a question.
    compare_models  Ask several models the same question in parallel and return
                    their answers side by side, with per-model errors reported.

Run over stdio (Claude Code, Codex, Cursor):
    uv run crossvet-mcp
Register in Claude Code:
    claude mcp add crossvet -- uv --directory /path/to/crossvet run crossvet-mcp

Model strings use the same format as REVIEW_MODELS (``openai:...``, ``anthropic:...``,
``google_genai:...``, ``openrouter:<model>``, ``ollama:<model>``, ``local:<model>``).
"""

from __future__ import annotations

import asyncio
import os
from typing import Any

from langchain_core.messages import HumanMessage
from mcp.server.fastmcp import FastMCP

from open_deep_research.cross_vendor_review import build_reviewer, parse_review_models

MAX_PROMPT_CHARS = 50_000
MAX_OUTPUT_TOKENS = 8_000
MAX_MODELS = 6

mcp = FastMCP("crossvet")


def _text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):  # content blocks
        return "".join(b.get("text", "") if isinstance(b, dict) else str(b) for b in content)
    return str(content)


def _validate(prompt: str, max_tokens: int) -> int:
    if not prompt or not prompt.strip():
        raise ValueError("prompt must not be empty")
    if len(prompt) > MAX_PROMPT_CHARS:
        raise ValueError(f"prompt is longer than {MAX_PROMPT_CHARS} characters")
    return max(1, min(int(max_tokens), MAX_OUTPUT_TOKENS))


async def _ask(model: str, prompt: str, max_tokens: int) -> str:
    llm = build_reviewer(model, max_tokens, {"configurable": {}})
    reply = await llm.ainvoke([HumanMessage(content=prompt)])
    return _text(reply.content)


@mcp.tool()
async def ask_model(model: str, prompt: str, max_tokens: int = 2000) -> str:
    """Ask a single model a question and return its answer.

    Args:
        model: provider:model string, e.g. "anthropic:claude-sonnet-4-5" or "ollama:llama3".
        prompt: the question or task.
        max_tokens: output limit (capped at 8000).
    """
    return await _ask(model, prompt, _validate(prompt, max_tokens))


@mcp.tool()
async def compare_models(prompt: str, models: list[str] | None = None, max_tokens: int = 2000) -> dict[str, Any]:
    """Ask several models the same question in parallel and return each answer.

    Args:
        prompt: the question or task.
        models: provider:model strings; defaults to REVIEW_MODELS from the environment.
        max_tokens: output limit per model (capped at 8000).

    Returns a mapping with "answers" (model -> text) and "errors" (model -> error type),
    so one failing provider never hides the others' answers.
    """
    limit = _validate(prompt, max_tokens)
    chosen = list(dict.fromkeys(models or parse_review_models(os.getenv("REVIEW_MODELS", ""))))
    if not chosen:
        raise ValueError("no models given and REVIEW_MODELS is empty")
    if len(chosen) > MAX_MODELS:
        raise ValueError(f"at most {MAX_MODELS} models per comparison")

    async def one(m: str) -> tuple[str, str | None, str | None]:
        try:
            return m, await _ask(m, prompt, limit), None
        except Exception as exc:
            return m, None, type(exc).__name__

    results = await asyncio.gather(*(one(m) for m in chosen))
    return {
        "answers": {m: a for m, a, _ in results if a is not None},
        "errors": {m: e for m, _, e in results if e is not None},
    }


def main() -> None:
    """Entry point: serve over stdio."""
    mcp.run()


if __name__ == "__main__":
    main()
