"""Optional human approval step between research and the final report.

When ``require_approval`` is on, the graph pauses after research with a LangGraph
``interrupt``. The payload follows the HITL request format Agent Chat UI renders
(``action_requests`` + ``review_configs``), so the web UI shows approve / edit /
reject controls. The CLI and other clients can resume with the same
``{"decisions": [...]}`` shape, or with a plain bool / string.

Resume semantics:
    approve                       write the report as planned
    edit (args.instructions=...)  write the report, following extra instructions
    reject (message=...)          stop without writing a report
"""

from __future__ import annotations

import re
from typing import Any, Literal

from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.runnables import RunnableConfig
from langgraph.graph import END
from langgraph.types import Command, interrupt

from open_deep_research.configuration import Configuration

ACTION_NAME = "write_final_report"
URL_RE = re.compile(r"https?://[^\s\)\]>\"']+")


def count_sources(notes: list[str]) -> int:
    """Count distinct URLs mentioned in the research notes."""
    return len({u.rstrip(".,;:").rstrip("/") for n in notes for u in URL_RE.findall(n or "")})


def build_approval_request(state: dict[str, Any]) -> dict[str, Any]:
    """Build an Agent Chat UI compatible HITL request describing the pending report."""
    notes = state.get("notes", []) or []
    raw = state.get("raw_notes", []) or []
    preview = "\n\n".join(notes)[:1500]
    return {
        "action_requests": [
            {
                "name": ACTION_NAME,
                "args": {
                    "research_brief": state.get("research_brief", "") or "",
                    "sources_found": count_sources(raw or notes),
                    "findings_preview": preview,
                    "instructions": "",
                },
                "description": (
                    "Research is complete. Approve to write the final report, edit "
                    "'instructions' to steer it (focus, length, audience), or reject to stop."
                ),
            }
        ],
        "review_configs": [{"action_name": ACTION_NAME, "allowed_decisions": ["approve", "edit", "reject"]}],
    }


def parse_decision(resume: Any) -> tuple[str, str, str]:
    """Normalize a resume value into (decision, instructions, message).

    Accepts the Agent Chat UI shape ``{"decisions": [...]}``, a single decision dict,
    ``True``/``False``, or a string (treated as approve-with-instructions). Anything
    unrecognized is treated as a rejection, so an ambiguous answer never spends money.
    """
    if isinstance(resume, bool):
        return ("approve", "", "") if resume else ("reject", "", "Rejected by reviewer.")
    if isinstance(resume, str):
        text = resume.strip()
        return ("approve", text, "") if text else ("approve", "", "")
    if isinstance(resume, dict) and "decisions" in resume:
        decisions = resume.get("decisions") or []
        resume = decisions[0] if decisions else None
    if isinstance(resume, dict):
        kind = resume.get("type")
        if kind == "approve":
            return "approve", "", ""
        if kind == "edit":
            args = (resume.get("edited_action") or {}).get("args") or {}
            return "approve", str(args.get("instructions", "") or "").strip(), ""
        if kind == "reject":
            return "reject", "", str(resume.get("message") or "Rejected by reviewer.")
    return "reject", "", "Unrecognized approval response; nothing was written."


async def approve_research(
    state: dict[str, Any], config: RunnableConfig
) -> Command[Literal["final_report_generation", "__end__"]]:
    """LangGraph node: pause for human approval when enabled, then route."""
    configurable = Configuration.from_runnable_config(config)
    if not configurable.require_approval:
        return Command(goto="final_report_generation")

    decision, instructions, message = parse_decision(interrupt(build_approval_request(state)))
    if decision == "reject":
        text = f"Report not written: {message}"
        return Command(goto=END, update={"final_report": text, "messages": [AIMessage(content=text)]})
    if instructions:
        note = HumanMessage(content=f"Additional instructions for the final report: {instructions}")
        return Command(goto="final_report_generation", update={"messages": [note]})
    return Command(goto="final_report_generation")
