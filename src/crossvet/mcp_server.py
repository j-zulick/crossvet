"""MCP server: three tools for Cursor, Claude Code, Codex or any MCP client.

    list_models    your models, their short names, prices, and the default
    ask_model      ask one named model (or the default); the answer ends with its model, tokens and cost
    recent_turns   the latest questions and answers across every app that uses Crossvet

The assistant you are talking to calls these tools; Crossvet calls the other vendor's API. No model
gets a shell, and Crossvet never chooses the model.

    crossvet mcp            stdio (Claude Code, Codex, Cursor, Claude Desktop)
    crossvet mcp --http     Streamable HTTP on 127.0.0.1:8788 (this computer only)
"""

from __future__ import annotations

import sys
from typing import Any

from crossvet import __version__
from crossvet.core import Crossvet
from crossvet.providers import ProviderError

MAX_TEXT = 60_000  # characters of one request sent through ask_model


def tools(cv: Crossvet) -> dict[str, Any]:
    """Return the three tool functions, bound to one :class:`Crossvet`."""

    def list_models() -> str:
        """List the models you can ask by name: full provider:model names, short names, prices and the default."""
        return cv.models_text()

    def ask_model(request: str, model: str = "default", system: str = "") -> str:
        """Ask one model and return its answer.

        Args:
            request: what to ask, with any context the model needs (it does not see this conversation).
            model: a provider:model name (anthropic:claude-opus-5-5), a short name (opus, sol), or "default".
            system: optional instructions for the model.
        """
        if len(request) > MAX_TEXT:
            return f"The request is {len(request):,} characters; the limit is {MAX_TEXT:,}. Shorten it."
        messages = ([{"role": "system", "content": system}] if system else []) + [{"role": "user", "content": request}]
        try:
            answer = cv.ask(model, messages, app="mcp")
        except (ProviderError, RuntimeError, ValueError) as exc:
            return f"Crossvet could not get an answer from {model}: {exc}"
        return f"{answer.text}\n\n[crossvet: {answer.footer()}]"

    def recent_turns(limit: int = 10) -> str:
        """Show the latest questions and answers across every app that uses Crossvet, newest first."""
        turns = cv.store.recent(max(1, min(int(limit), 50)))
        if not turns:
            return "No turns yet."
        lines = []
        for t in turns:
            who = t.model if t.role == "assistant" else f"question via {t.author}"
            text = t.content if len(t.content) <= 400 else t.content[:400] + "..."
            lines.append(f"#{t.id} [{who}] {text}")
        return "\n".join(lines)

    return {"list_models": list_models, "ask_model": ask_model, "recent_turns": recent_turns}


def sdk_major() -> int:
    """Return the installed MCP Python SDK's major version (1 or 2)."""
    try:
        import mcp.server.mcpserver  # noqa: F401  (SDK 2.x)
    except ImportError:
        return 1
    return 2


def build_server(cv: Crossvet | None = None, host: str = "127.0.0.1", port: int = 8788) -> Any:
    """Create the MCP server: ``MCPServer`` on SDK 2.x, ``FastMCP`` on 1.x."""
    instructions = (f"Crossvet {__version__}: ask any model by name. list_models shows them; ask_model asks one; "
                    "recent_turns shows what was asked across apps.")
    if sdk_major() == 1:
        from mcp.server.fastmcp import FastMCP

        server = FastMCP("crossvet", instructions=instructions, host=host, port=port)
        server.crossvet_http = {}
    else:
        from mcp.server.mcpserver import MCPServer

        server = MCPServer("crossvet", instructions=instructions, version=__version__)
        server.crossvet_http = {"host": host, "port": port}
    for name, function in tools(cv or Crossvet()).items():
        server.tool(name=name)(function)
    return server


def main(http: bool = False, host: str = "127.0.0.1", port: int = 8788) -> int:
    """Run the MCP server over stdio, or Streamable HTTP on this computer with ``http``."""
    if http and host not in ("127.0.0.1", "localhost", "::1"):
        print("the HTTP transport only listens on this computer (127.0.0.1, localhost or ::1)", file=sys.stderr)
        return 2
    server = build_server(host=host, port=port)
    if http:
        server.run(transport="streamable-http", **server.crossvet_http)
    else:
        server.run(transport="stdio")
    return 0
