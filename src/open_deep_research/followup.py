"""Follow-up questions on a finished run, answered only from that run's research notes.

A follow-up reuses what the run already read: no new searching, one model call. The
answer must cite URLs from the notes, and the same citation check as the report flags
any URL the run never read. If the notes don't cover the question, the model is told to
say so rather than answer from memory.
"""

from __future__ import annotations

from typing import Any, Awaitable, Callable

from open_deep_research.cross_vendor_review import check_citations

FOLLOWUP_PROMPT = """You answer a follow-up question about a finished research report. Use ONLY the research notes and the report below; do not use outside knowledge.

Rules:
- Cite sources as markdown links, using only URLs that appear in the research notes.
- If the notes do not answer the question, say "The research for this report does not cover that." and, in one sentence, say what new research would be needed.
- Be concise: answer the question directly, then the supporting evidence.

Research brief:
{brief}

Research notes:
{notes}

Report:
{report}

Follow-up question: {question}"""

NOT_COVERED = "The research for this report does not cover that."

Ask = Callable[[str], Awaitable[str]]
"""ask(prompt) -> answer text."""


def run_notes(values: dict[str, Any]) -> str:
    """Return the research notes saved in a run's state (raw notes first, as review uses them)."""
    return "\n\n".join(values.get("raw_notes") or values.get("notes") or [])


async def answer(question: str, values: dict[str, Any], ask: Ask, max_notes_chars: int = 120_000) -> dict[str, Any]:
    """Answer ``question`` from a run's saved state; returns answer, flagged URLs and coverage."""
    report = values.get("final_report") or ""
    notes = run_notes(values)
    if not report and not notes:
        raise ValueError("This run has no report or research notes yet; finish or resume it first.")
    prompt = FOLLOWUP_PROMPT.format(
        brief=values.get("research_brief") or "",
        notes=notes[:max_notes_chars],
        report=report[:40_000],
        question=question.strip(),
    )
    text = (await ask(prompt)).strip()
    return {
        "question": question.strip(),
        "answer": text,
        "flagged_urls": check_citations(text, notes),
        "covered": NOT_COVERED.lower() not in text.lower(),
    }


def render(result: dict[str, Any]) -> str:
    """Markdown for printing or saving a follow-up."""
    out = f"## Follow-up: {result['question']}\n\n{result['answer']}\n"
    if result["flagged_urls"]:
        out += "\n**Citation check:** these URLs were not read during the research: " + ", ".join(result["flagged_urls"]) + "\n"
    return out


def model_asker(model: str, max_tokens: int, config: dict[str, Any] | None = None) -> Ask:
    """Build an ``Ask`` backed by one chat model (the run's final-report model by default)."""
    from langchain.chat_models import init_chat_model
    from langchain_core.messages import HumanMessage

    from open_deep_research.utils import get_api_key_for_model

    llm = init_chat_model(model=model, max_tokens=max_tokens, api_key=get_api_key_for_model(model, config or {}))

    async def ask(prompt: str) -> str:
        msg = await llm.ainvoke([HumanMessage(content=prompt)])
        content = msg.content
        if isinstance(content, list):
            return "".join(b.get("text", "") if isinstance(b, dict) else str(b) for b in content)
        return str(content)

    return ask
