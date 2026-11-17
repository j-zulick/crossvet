"""Search provider backed by a self-hosted research gateway over MCP.

The gateway (SearXNG discovery + plain HTTP / Firecrawl / headless-browser reading) exposes a
``search_and_read`` tool over Streamable HTTP MCP. This module turns its
per-source results into the same "summarized sources" string the upstream
Tavily tool produces, so the rest of the Open Deep Research graph is unchanged.

Configuration (environment):
    RESEARCH_GATEWAY_URL    Full MCP endpoint, e.g. https://example.com/research/mcp
    RESEARCH_GATEWAY_TOKEN  Bearer token issued by the gateway (never logged)
    RESEARCH_GATEWAY_TOOL   Tool name to call (default: search_and_read)
"""

from __future__ import annotations

import asyncio
import json
import os
from dataclasses import dataclass, field
from typing import Any, List

from langchain_core.runnables import RunnableConfig
from langchain_core.tools import BaseTool, tool

DEFAULT_TOOL = "search_and_read"
GATEWAY_SEARCH_DESCRIPTION = (
    "Web search through a self-hosted research gateway (SearXNG discovery with "
    "plain HTTP, Firecrawl and headless-browser reading). Returns summarized "
    "sources with URLs and per-source read status."
)


@dataclass
class GatewaySource:
    """One source returned by the gateway, normalized from its JSON payload."""

    url: str
    title: str = ""
    content: str = ""
    snippet: str = ""
    engine: str | None = None
    status: str = "ok"
    extra: dict[str, Any] = field(default_factory=dict)


def gateway_settings() -> tuple[str | None, str | None, str]:
    """Return (url, token, tool_name) from the environment."""
    return (
        os.getenv("RESEARCH_GATEWAY_URL"),
        os.getenv("RESEARCH_GATEWAY_TOKEN"),
        os.getenv("RESEARCH_GATEWAY_TOOL", DEFAULT_TOOL),
    )


def _first(d: dict[str, Any], *keys: str, default: Any = "") -> Any:
    for k in keys:
        v = d.get(k)
        if v not in (None, ""):
            return v
    return default


def _coerce_payload(raw: Any) -> Any:
    """MCP tools may return a JSON string, a list of content blocks, or a dict."""
    if isinstance(raw, (dict, list)) and not (
        isinstance(raw, list) and raw and isinstance(raw[0], dict) and raw[0].get("type") == "text"
    ):
        return raw
    if isinstance(raw, list):  # list of {"type": "text", "text": "..."} blocks
        raw = "".join(b.get("text", "") for b in raw if isinstance(b, dict))
    if isinstance(raw, str):
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return {"sources": [], "status": "unparsed", "raw": raw[:2000]}
    return raw


def parse_gateway_response(raw: Any) -> list[GatewaySource]:
    """Normalize a gateway search_and_read payload into GatewaySource items.

    Tolerant of field-name variations so the adapter survives gateway releases:
    sources may live under ``sources``/``results``/``items``; text may be under
    ``read.markdown``, ``markdown``, ``text`` or ``content``.
    """
    payload = _coerce_payload(raw)
    if isinstance(payload, list):
        items = payload
    elif isinstance(payload, dict):
        items = _first(payload, "sources", "results", "items", default=[])
    else:
        items = []

    sources: list[GatewaySource] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        read = item.get("read") if isinstance(item.get("read"), dict) else {}
        url = _first(read, "final_url", "url") or _first(item, "final_url", "url")
        if not url:
            continue
        sources.append(
            GatewaySource(
                url=url,
                title=_first(read, "title") or _first(item, "title"),
                content=_first(read, "markdown", "text", "content") or _first(item, "markdown", "text", "content"),
                snippet=_first(item, "snippet", "description"),
                engine=_first(item, "engine", default=None),
                status=_first(read, "status") or _first(item, "status", default="ok"),
                extra={
                    **{k: item[k] for k in ("rank", "evidence_id", "page_id") if k in item},
                    **{k: read[k] for k in ("extractor", "outcome", "truncated", "retrieved_at", "escalation_reason") if read.get(k) is not None},
                },
            )
        )
    return sources


async def load_gateway_tool() -> BaseTool:
    """Connect to the gateway over Streamable HTTP MCP and return its search tool."""
    from langchain_mcp_adapters.client import MultiServerMCPClient

    url, token, tool_name = gateway_settings()
    if not url or not token:
        raise RuntimeError("RESEARCH_GATEWAY_URL and RESEARCH_GATEWAY_TOKEN must be set to use search_api=gateway")
    client = MultiServerMCPClient(
        {
            "research_gateway": {
                "url": url,
                "transport": "streamable_http",
                "headers": {"Authorization": f"Bearer {token}"},
            }
        }
    )
    tools = await client.get_tools()
    for t in tools:
        if t.name == tool_name:
            return t
    raise RuntimeError(f"Gateway does not expose tool '{tool_name}'. Available: {[t.name for t in tools]}")


def _tool_args(gateway_tool: BaseTool, query: str, max_results: int) -> dict[str, Any]:
    """Build arguments that match whatever schema the gateway tool advertises."""
    schema = gateway_tool.args or {}
    args: dict[str, Any] = {"query": query}
    for name in ("num_read", "max_sources", "num_results", "max_results", "limit"):
        if name in schema:
            args[name] = max_results
            break
    return args


async def gateway_search_raw(queries: List[str], max_results: int = 5) -> list[tuple[str, list[GatewaySource]]]:
    """Run each query through the gateway in parallel; failures become empty lists."""
    gateway_tool = await load_gateway_tool()

    async def one(q: str) -> tuple[str, list[GatewaySource]]:
        try:
            raw = await gateway_tool.ainvoke(_tool_args(gateway_tool, q, max_results))
            return q, parse_gateway_response(raw)
        except Exception as exc:  # one bad query must not sink the batch
            return q, [GatewaySource(url=f"error://{q}", status=f"error:{type(exc).__name__}")]

    return await asyncio.gather(*(one(q) for q in queries))


@tool(description=GATEWAY_SEARCH_DESCRIPTION)
async def gateway_search(queries: List[str], config: RunnableConfig = None) -> str:
    """Search via the research gateway and return summarized, source-labelled results."""
    # Local imports avoid a circular import with utils.
    from open_deep_research.configuration import Configuration
    from open_deep_research.state import Summary
    from open_deep_research.utils import (
        stage_chat_model,
        structured_output_kwargs,
        summarize_webpage,
    )

    batches = await gateway_search_raw(queries)
    unique: dict[str, tuple[str, GatewaySource]] = {}
    failures: list[str] = []
    for query, sources in batches:
        for s in sources:
            if s.url.startswith("error://"):
                failures.append(f"{query}: {s.status}")
            elif s.url not in unique:
                unique[s.url] = (query, s)

    if not unique:
        return "No valid search results found from the research gateway." + (
            f" Failures: {'; '.join(failures)}" if failures else ""
        )

    configurable = Configuration.from_runnable_config(config)
    model = stage_chat_model(
        configurable.summarization_model,
        configurable.summarization_model_max_tokens,
        config,
        tags=["langsmith:nostream"],
    ).with_structured_output(Summary, **structured_output_kwargs(configurable.summarization_model)).with_retry(stop_after_attempt=configurable.max_structured_output_retries)

    async def summarize(s: GatewaySource) -> str | None:
        if not s.content:
            return None
        return await summarize_webpage(model, s.content[: configurable.max_content_length])

    summaries = await asyncio.gather(*(summarize(s) for _, s in unique.values()))

    out = ["Search results (research gateway):\n"]
    for i, ((url, (_, s)), summary) in enumerate(zip(unique.items(), summaries), start=1):
        body = summary or s.content[:2000] or s.snippet
        meta = ", ".join(x for x in (f"engine={s.engine}" if s.engine else "", f"read={s.status}") if x)
        out.append(f"\n--- SOURCE {i}: {s.title or url} ---\nURL: {url}\n({meta})\n\nSUMMARY:\n{body}\n\n" + "-" * 80)
    if failures:
        out.append("\nGateway query failures: " + "; ".join(failures))
    return "\n".join(out)
