"""Deep Agents edition: research with LangChain's ``deepagents``, then the same review.

The LangGraph edition (``deep_researcher``) hard-codes its research loop: brief →
supervisor → parallel researchers → compression → report. This edition hands the
research and drafting to a Deep Agent instead, which plans with a to-do list,
delegates focused questions to researcher sub-agents and keeps working notes in a
virtual filesystem. The draft then goes through the identical cross-vendor review.

Grounding is not left to the agent: every search result returned to the agent or any
sub-agent is captured by a callback and becomes the research notes the citation check,
critic and deliberation are verified against.

Graph id: ``deep_agent`` (see ``langgraph.json``). Configuration is shared with the
LangGraph edition: ``RESEARCH_MODEL`` drives the agent, ``SEARCH_API`` picks search
(``tavily``, ``gateway``, or the model's built-in ``openai`` / ``anthropic`` search, whose
sources are read from the model's replies),
and every ``REVIEW_*`` setting applies unchanged.
"""

from __future__ import annotations

import operator
from typing import Annotated, Any, TypedDict

from langchain_core.callbacks import AsyncCallbackHandler
from langchain_core.messages import AIMessage, AnyMessage, HumanMessage
from langchain_core.runnables import RunnableConfig
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages

from open_deep_research.configuration import Configuration, SearchAPI
from open_deep_research.cross_vendor_review import build_reviewer, cross_vendor_review
from open_deep_research.utils import get_config_value, get_search_tool, get_today_str

REPORT_PATH = "/report.md"

AGENT_PROMPT = """You are a careful research analyst. Today is {date}.

Answer the user's question with a well-sourced research report.

1. Plan the work with your to-do list.
2. Delegate focused sub-questions to the `researcher` sub-agent; run independent ones in parallel.
3. Keep working notes in files if that helps you organize.
4. Write the final report in Markdown to the file {report_path}: a title, clear sections, inline citations like [1], and a final "### Sources" list with one URL per entry.

Cite only URLs that appeared in search results. Do not invent sources. When the report is written, reply with a one-line confirmation."""

RESEARCHER_PROMPT = """You research one focused question. Today is {date}.
Search the web, read the results, and reply with a concise summary of what you found. Quote key facts and give the URL for every fact. Stop after a few searches once you can answer; say plainly what you could not find."""


class SourceCollector(AsyncCallbackHandler):
    """Capture the output of every search tool call, including inside sub-agents."""

    def __init__(self, tool_names: set[str]) -> None:  # noqa: D107
        self.tool_names = tool_names
        self.names: dict[Any, str] = {}
        self.outputs: list[str] = []

    async def on_tool_start(self, serialized: dict[str, Any], input_str: str, *, run_id: Any, **kwargs: Any) -> None:  # noqa: D102
        self.names[run_id] = (serialized or {}).get("name") or kwargs.get("name") or ""

    async def on_tool_end(self, output: Any, *, run_id: Any, **kwargs: Any) -> None:  # noqa: D102
        name = self.names.pop(run_id, "") or kwargs.get("name") or ""
        if name in self.tool_names:
            content = getattr(output, "content", output)
            self.outputs.append(content if isinstance(content, str) else str(content))

    async def on_llm_end(self, response: Any, **kwargs: Any) -> None:  # noqa: D102
        """Built-in model search (OpenAI, Anthropic) is not a tool call: keep its sources from the reply."""
        for gens in getattr(response, "generations", []) or []:
            for gen in gens:
                content = getattr(getattr(gen, "message", None), "content", None)
                if isinstance(content, list):
                    found = native_sources(content)
                    if found:
                        self.outputs.append(found)


def native_sources(blocks: list[Any]) -> str:
    """Return the sources in built-in search content blocks (OpenAI and Anthropic) as note lines."""
    lines: list[str] = []
    for b in blocks:
        if not isinstance(b, dict):
            continue
        kind = b.get("type")
        if kind == "web_search_call":
            for src in (b.get("action") or {}).get("sources") or []:
                if isinstance(src, dict) and src.get("url"):
                    lines.append(f"Source consulted: {src['url']}")
        elif kind == "web_search_tool_result":
            for item in b.get("content") or []:
                if isinstance(item, dict) and item.get("url"):
                    lines.append(f"Source consulted: {item.get('title', '')} {item['url']}".strip())
        elif kind == "text":
            for ann in b.get("annotations") or []:
                if isinstance(ann, dict) and ann.get("url"):
                    lines.append(f"Cited: {ann.get('title', '')} {ann['url']}".strip())
            for cit in b.get("citations") or []:
                if isinstance(cit, dict) and cit.get("url"):
                    lines.append(f"Cited: {cit.get('cited_text', '')} {cit['url']}".strip())
            if lines and b.get("text"):
                lines.append(b["text"])
    return "\n".join(lines)


class DeepAgentState(TypedDict, total=False):
    """State of the Deep Agents edition graph."""

    messages: Annotated[list[AnyMessage], add_messages]
    research_brief: str
    raw_notes: Annotated[list[str], operator.add]
    final_report: str
    review: dict[str, Any]


class DeepAgentInput(TypedDict):
    """Input: the conversation, ending with the research question."""

    messages: Annotated[list[AnyMessage], add_messages]


class DeepAgentOutput(TypedDict, total=False):
    """Output: the reviewed report and review summary."""

    messages: Annotated[list[AnyMessage], add_messages]
    final_report: str
    review: dict[str, Any]


def _text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(p.get("text", "") if isinstance(p, dict) else str(p) for p in content)
    return str(content or "")


def report_from(result: dict[str, Any]) -> str:
    """Prefer the report file the agent wrote; fall back to its last message."""
    files = result.get("files") or {}
    data = files.get(REPORT_PATH)
    if data:
        content = data.get("content", "") if isinstance(data, dict) else data
        text = "\n".join(content) if isinstance(content, list) else str(content)
        if text.strip():
            return text
    for msg in reversed(result.get("messages") or []):
        if isinstance(msg, AIMessage) and _text(msg.content).strip():
            return _text(msg.content)
    return ""


def report_stop_problem(result: dict[str, Any]) -> str:
    """Why the reply that produced the report stopped early, or "" when it finished.

    Checks the message that wrote the report file (or, without one, the agent's last message)
    for an output limit or a provider content filter.
    """
    from open_deep_research.models import stop_problem

    msgs = [m for m in (result.get("messages") or []) if isinstance(m, AIMessage)]
    for msg in reversed(msgs):
        for call in getattr(msg, "tool_calls", None) or []:
            if str((call.get("args") or {}).get("file_path", "")).endswith(REPORT_PATH.lstrip("/")):
                return stop_problem(msg)
    return stop_problem(msgs[-1]) if msgs else ""


def build_agent(model: Any, search_tools: list[Any], researcher_model: Any = None) -> Any:
    """Create the Deep Agent (the orchestrator) with a researcher sub-agent.

    ``researcher_model`` lets the sub-agent run on a different model than the orchestrator.
    """
    from deepagents import create_deep_agent

    date = get_today_str()
    researcher = {
        "name": "researcher",
        "description": "Researches one focused sub-question on the web and returns a summary with a URL for every fact.",
        "system_prompt": RESEARCHER_PROMPT.format(date=date),
        "tools": search_tools,
    }
    if researcher_model is not None:
        researcher["model"] = researcher_model
    return create_deep_agent(
        model=model,
        tools=search_tools,
        system_prompt=AGENT_PROMPT.format(date=date, report_path=REPORT_PATH),
        subagents=[researcher],
        name="crossvet-deep-agent",
    )


async def deep_research(state: DeepAgentState, config: RunnableConfig) -> dict[str, Any]:
    """LangGraph node: run the Deep Agent and collect its report and search results."""
    configurable = Configuration.from_runnable_config(config)
    search_tools = await get_search_tool(SearchAPI(get_config_value(configurable.search_api)))
    names = {t.name for t in search_tools if hasattr(t, "name")}
    orchestrator, researcher = configurable.model_for("supervisor"), configurable.model_for("researcher")
    model = build_reviewer(orchestrator, configurable.research_model_max_tokens, config)
    sub_model = None if researcher == orchestrator else build_reviewer(researcher, configurable.research_model_max_tokens, config)
    if get_config_value(configurable.search_api) == "openai":
        for m in (model, sub_model):
            if m is not None and hasattr(m, "include"):
                m.include = ["web_search_call.action.sources"]  # return every consulted source
    agent = build_agent(model, search_tools, sub_model)
    collector = SourceCollector(names)
    messages = state.get("messages") or []
    question = next((_text(m.content) for m in reversed(messages) if isinstance(m, HumanMessage)), "")
    from open_deep_research.context import with_context

    brief = with_context(question, configurable.context_pack, configurable.research_context)
    if brief != question:
        messages = [*messages, HumanMessage(content=brief[len(question):].strip())]
    try:
        result = await agent.with_config({"callbacks": [collector], "recursion_limit": 300}).ainvoke({"messages": messages}, config)
        report = report_from(result)
        problem = report_stop_problem(result)
        if problem and report:
            report += f"\n\n> **Incomplete report:** the agent's reply stopped early ({problem}). Check the sources directly.\n"
    except Exception as exc:
        report = f"Error generating final report: {type(exc).__name__}: {exc}"
    return {
        "research_brief": brief,
        "raw_notes": collector.outputs,
        "final_report": report,
        "messages": [AIMessage(content=report)],
    }


builder = StateGraph(DeepAgentState, input_schema=DeepAgentInput, output_schema=DeepAgentOutput)
builder.add_node("deep_research", deep_research)
builder.add_node("cross_vendor_review", cross_vendor_review)
builder.add_edge(START, "deep_research")
builder.add_edge("deep_research", "cross_vendor_review")
builder.add_edge("cross_vendor_review", END)
deep_agent = builder.compile()
