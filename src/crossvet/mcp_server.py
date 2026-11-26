"""MCP server: tools for Cursor, Claude Code, Codex or any MCP client.

    list_models      your models, their short names, prices, and the default
    ask_model        ask one named model (or the default); the answer ends with its model, tokens and cost
    recent_turns     the latest questions and answers across every app that uses Crossvet
    ask              let Crossvet choose the model (auto); explain_route shows the choice without calling
    compare_models   the same request to several models; challenge: another vendor tries to break an answer
    rate_answer      rate an answer good or bad (tunes auto's routes, only when you accept a change)
    save_note, search_memory, load_context   notes shared by every app
    handoff_submit, handoff_status, handoff_result   hand a task to Claude Code or Codex on this computer

The assistant you are talking to calls these tools; Crossvet calls the other vendor's API. No model
gets a shell. Crossvet chooses a model only in ``ask`` (and when you name auto, a slot or a goal).

    crossvet mcp            stdio (Claude Code, Codex, Cursor, Claude Desktop)
    crossvet mcp --http     Streamable HTTP on 127.0.0.1:8788 (this computer only)
"""

from __future__ import annotations

import sys
from typing import Any

from crossvet import __version__, handoff, multi
from crossvet.core import Crossvet
from crossvet.providers import ProviderError

MAX_TEXT = 60_000  # characters of one request sent through ask_model


def tools(cv: Crossvet) -> dict[str, Any]:
    """Return the tool functions, bound to one :class:`Crossvet`."""

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

    def ask(request: str, system: str = "") -> str:
        """Ask and let Crossvet choose the model from the kind of request (auto); the answer says which model and why.

        Args:
            request: what to ask, with any context the model needs.
            system: optional instructions for the model.
        """
        return ask_model(request, "auto", system)

    def explain_route(request: str) -> str:
        """Show which model auto would choose for a request, and why, without calling any model."""
        try:
            return cv.decide("auto", [{"role": "user", "content": request[:MAX_TEXT]}]).explain()
        except ValueError as exc:
            return str(exc)

    def compare_models(request: str, models: str) -> str:
        """Ask two to six models the same request and show the answers side by side.

        Args:
            request: what to ask.
            models: model names separated by commas (for example "opus, sol").
        """
        if len(request) > MAX_TEXT:
            return f"The request is {len(request):,} characters; the limit is {MAX_TEXT:,}."
        try:
            return multi.compare_text(multi.compare(cv, [m.strip() for m in models.split(",") if m.strip()], request, app="mcp"))
        except (ProviderError, ValueError) as exc:
            return f"Crossvet could not compare: {exc}"

    def challenge(question: str, answer: str, author_model: str = "", challenger: str = "") -> str:
        """Have a model from another vendor try to break an answer; returns its verdict and the problems it found."""
        try:
            return multi.challenge_text(multi.challenge(cv, question[:MAX_TEXT], answer[:MAX_TEXT], author_model, challenger))
        except (ProviderError, RuntimeError, ValueError) as exc:
            return f"Crossvet could not get a challenge: {exc}"

    def rate_answer(turn: int, rating: str, note: str = "") -> str:
        """Rate an answer by its turn number (shown by recent_turns): rating is "good" or "bad"."""
        value = {"good": 1, "bad": -1, "+1": 1, "-1": -1}.get(rating.strip().lower())
        if value is None:
            return 'rating must be "good" or "bad"'
        cv.lab.rate(int(turn), value, note, source="mcp")
        return f"Rated #{turn} {rating}."

    def save_note(text: str, tags: str = "") -> str:
        """Save a note that every app using Crossvet can find later."""
        try:
            return f"Saved note #{cv.lab.save_note(text, tags)}."
        except ValueError as exc:
            return str(exc)

    def search_memory(query: str) -> str:
        """Find saved notes that match the words in a query."""
        found = cv.lab.search_notes(query)
        return "\n".join(f"#{n['id']} {n['text']}" for n in found) or "No matching notes."

    def load_context(query: str) -> str:
        """Collect what Crossvet knows about a topic: matching notes and recent answers that mention it."""
        notes = cv.lab.search_notes(query, limit=5)
        words = [w.lower() for w in query.split() if len(w) > 3]
        turns = [t for t in cv.store.recent(200) if t.role == "assistant" and any(w in t.content.lower() for w in words)][:5]
        parts = [f"note #{n['id']}: {n['text']}" for n in notes]
        parts += [f"answer #{t.id} ({t.model}): {t.content[:600]}" for t in turns]
        return "\n\n".join(parts) or "Nothing saved about that yet."

    def handoff_submit(agent: str, task: str, cwd: str = ".") -> str:
        """Hand a task to a coding agent on this computer ("claude-code" or "codex"); returns a handoff number."""
        try:
            return f"Handoff #{handoff.submit(cv.lab, agent, task, cwd)} started; handoff_status shows progress."
        except ValueError as exc:
            return str(exc)

    def handoff_status(handoff_id: int) -> str:
        """Show whether a handoff is running, done or failed."""
        return handoff.describe(cv.lab, int(handoff_id))

    def handoff_result(handoff_id: int) -> str:
        """Show a handoff's status and the agent's output."""
        return handoff.describe(cv.lab, int(handoff_id), with_result=True)

    return {"list_models": list_models, "ask_model": ask_model, "recent_turns": recent_turns, "ask": ask,
            "explain_route": explain_route, "compare_models": compare_models, "challenge": challenge,
            "rate_answer": rate_answer, "save_note": save_note, "search_memory": search_memory,
            "load_context": load_context, "handoff_submit": handoff_submit, "handoff_status": handoff_status,
            "handoff_result": handoff_result}


def sdk_major() -> int:
    """Return the installed MCP Python SDK's major version (1 or 2)."""
    try:
        import mcp.server.mcpserver  # noqa: F401  (SDK 2.x)
    except ImportError:
        return 1
    return 2


def build_server(cv: Crossvet | None = None, host: str = "127.0.0.1", port: int = 8788) -> Any:
    """Create the MCP server: ``MCPServer`` on SDK 2.x, ``FastMCP`` on 1.x."""
    instructions = (f"Crossvet {__version__}: ask any model by name (list_models, ask_model), or let Crossvet choose "
                    "(ask, explain_route). compare_models and challenge use several vendors; recent_turns, rate_answer "
                    "and the note tools are shared by every app.")
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
