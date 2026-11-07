"""Cross-vendor review council for the final research report.

After the draft report is written, reviewer models from different vendors:

1. **Critique** the draft independently (in parallel), as typed ``Critique`` objects.
2. **Vote**: critiques are anonymized and shuffled, then every reviewer ranks
   them by usefulness. Rankings are combined with a confidence-weighted Borda count.
3. **Citation check**: a deterministic pass flags URLs cited in the report that
   never appeared in the gathered research notes.
4. **Revise**: the report writer applies the top-ranked critiques, and a
   "Review notes" section records adopted points, dissent, and citation flags.

Anonymized peer review is inspired by Andrej Karpathy's llm-council; this module
is an independent implementation (see NOTICES.md).
"""

from __future__ import annotations

import asyncio
import os
import random
import re
from collections import defaultdict
from typing import Any

from langchain.chat_models import init_chat_model
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.runnables import RunnableConfig
from pydantic import BaseModel, Field

from open_deep_research.configuration import Configuration
from open_deep_research.utils import get_api_key_for_model, get_today_str

URL_RE = re.compile(r"https?://[^\s\)\]>\"']+")


###################
# Structured outputs
###################
class Critique(BaseModel):
    """One reviewer's critique of the draft report."""

    unsupported_claims: list[str] = Field(default_factory=list, description="Claims in the report not supported by the cited sources or research notes.")
    factual_concerns: list[str] = Field(default_factory=list, description="Statements that look wrong, outdated, or overstated.")
    missing_perspectives: list[str] = Field(default_factory=list, description="Important angles, counter-evidence, or sources the report omits.")
    suggested_revisions: list[str] = Field(default_factory=list, description="Concrete edits that would most improve the report.")
    overall_score: int = Field(ge=1, le=10, description="Overall quality of the draft, 1-10.")


class Ballot(BaseModel):
    """A reviewer's ranking of the anonymized critiques."""

    ranking: list[str] = Field(description="Critique ids ordered from most to least useful, e.g. ['C2','C1','C3'].")
    confidence: float = Field(ge=0.0, le=1.0, description="Confidence in this ranking, 0-1.")
    rationale: str = Field(default="", description="One or two sentences on why the top critique ranks first.")


###################
# Pure helpers (unit-tested)
###################
def parse_review_models(value: str) -> list[str]:
    """Split a comma-separated model list, dropping blanks."""
    return [m.strip() for m in (value or "").split(",") if m.strip()]


def anonymize(critiques: dict[str, Critique], seed: int | None = None) -> tuple[dict[str, Critique], dict[str, str]]:
    """Shuffle critiques and relabel them C1..Cn. Returns (by_label, label->model)."""
    rng = random.Random(seed)
    models = list(critiques)
    rng.shuffle(models)
    labels = {f"C{i}": m for i, m in enumerate(models, start=1)}
    return {lbl: critiques[m] for lbl, m in labels.items()}, labels


def weighted_borda(ballots: list[Ballot], labels: list[str]) -> list[tuple[str, float]]:
    """Confidence-weighted Borda count. Unknown labels are ignored; missing ones score 0."""
    valid = set(labels)
    n = len(labels)
    scores: dict[str, float] = defaultdict(float, {lbl: 0.0 for lbl in labels})
    for b in ballots:
        seen: list[str] = []
        for lbl in b.ranking:
            if lbl in valid and lbl not in seen:
                seen.append(lbl)
        for pos, lbl in enumerate(seen):
            scores[lbl] += (n - pos) * b.confidence
    return sorted(scores.items(), key=lambda kv: (-kv[1], kv[0]))


def check_citations(report: str, research_text: str) -> list[str]:
    """Return URLs cited in the report that do not appear anywhere in the research notes."""
    def norm(u: str) -> str:
        return u.rstrip(".,;:").rstrip("/")

    known = {norm(u) for u in URL_RE.findall(research_text or "")}
    flagged: list[str] = []
    for u in URL_RE.findall(report or ""):
        nu = norm(u)
        if nu not in known and nu not in flagged:
            flagged.append(nu)
    return flagged


def format_critique(c: Critique) -> str:
    """Render a critique as plain text for vote and revision prompts."""
    def block(title: str, items: list[str]) -> str:
        return f"{title}:\n" + ("\n".join(f"- {i}" for i in items) if items else "- (none)")
    return "\n".join([
        block("Unsupported claims", c.unsupported_claims),
        block("Factual concerns", c.factual_concerns),
        block("Missing perspectives", c.missing_perspectives),
        block("Suggested revisions", c.suggested_revisions),
        f"Overall score: {c.overall_score}/10",
    ])


###################
# Model construction
###################
def build_reviewer(model: str, max_tokens: int, config: RunnableConfig) -> BaseChatModel:
    """Create a chat model.

    Supports ``provider:model`` strings (e.g. ``ollama:gemma3`` for a model served by
    Ollama on this machine), ``openrouter:<model>``, and ``local:<model>`` for any
    OpenAI-compatible server (llama.cpp, LM Studio, MLX, vLLM) at LOCAL_LLM_BASE_URL.
    """
    if model.startswith("local:"):
        from langchain_openai import ChatOpenAI

        return ChatOpenAI(
            model=model.split(":", 1)[1],
            base_url=os.getenv("LOCAL_LLM_BASE_URL", "http://localhost:8080/v1"),
            api_key=os.getenv("LOCAL_LLM_API_KEY", "not-needed"),
            max_tokens=max_tokens,
        )
    if model.startswith("openrouter:"):
        from langchain_openai import ChatOpenAI

        return ChatOpenAI(
            model=model.split(":", 1)[1],
            base_url="https://openrouter.ai/api/v1",
            api_key=os.getenv("OPENROUTER_API_KEY"),
            max_tokens=max_tokens,
        )
    return init_chat_model(model=model, max_tokens=max_tokens, api_key=get_api_key_for_model(model, config))


###################
# Prompts
###################
CRITIQUE_PROMPT = """You are one of several independent reviewers checking a research report. Today is {date}.

Research question / brief:
{brief}

Research notes the report was written from (sources and findings):
{notes}

Draft report:
{report}

Review the draft strictly against the research notes. Flag claims the notes do not support, statements that look wrong or overstated, and important missing perspectives. Suggest concrete revisions. Be specific and brief."""

VOTE_PROMPT = """Several anonymous reviewers critiqued the same research report. Rank their critiques from most to least useful for improving the report's accuracy and completeness. Judge only the critiques' content.

Draft report (for context):
{report}

Critiques:
{critiques}

Return every critique id exactly once in your ranking."""

REVISE_PROMPT = """Revise the research report below using the reviewer feedback, which is listed in order of peer-voted usefulness. Today is {date}.

Rules:
- Only keep claims supported by the research notes; remove or qualify unsupported ones.
- Keep the original structure, citations and source list format unless a fix requires a change.
- Do not invent new sources or URLs.
- Do not add a review section; it is appended separately.

Research notes:
{notes}

Draft report:
{report}

Reviewer feedback (most useful first):
{feedback}

Return only the revised report in Markdown."""


###################
# Graph node
###################
async def cross_vendor_review(state: dict[str, Any], config: RunnableConfig) -> dict[str, Any]:
    """LangGraph node: critique → anonymized vote → citation check → revision."""
    configurable = Configuration.from_runnable_config(config)
    models = parse_review_models(configurable.review_models)
    report = state.get("final_report", "") or ""
    if not configurable.cross_vendor_review_enabled or len(models) < 2 or not report or report.startswith("Error generating final report"):
        return {}

    notes = "\n\n".join(state.get("raw_notes", []) or state.get("notes", []) or [])
    notes_for_prompt = notes[: configurable.max_content_length]
    brief = state.get("research_brief", "") or ""
    max_tokens = configurable.review_model_max_tokens
    retries = configurable.max_structured_output_retries

    # 1. Independent critiques in parallel; a failing reviewer is dropped (quorum >= 2).
    async def critique(model: str) -> tuple[str, Critique | None]:
        try:
            llm = build_reviewer(model, max_tokens, config).with_structured_output(Critique).with_retry(stop_after_attempt=retries)
            prompt = CRITIQUE_PROMPT.format(date=get_today_str(), brief=brief, notes=notes_for_prompt, report=report)
            return model, await llm.ainvoke([HumanMessage(content=prompt)])
        except Exception:
            return model, None

    results = await asyncio.gather(*(critique(m) for m in models))
    critiques = {m: c for m, c in results if c is not None}
    failed = [m for m, c in results if c is None]
    if len(critiques) < 2:
        return {"review": {"status": "skipped_no_quorum", "reviewers": models, "failed": failed}}

    # 2. Anonymized, shuffled vote by every successful reviewer.
    by_label, label_to_model = anonymize(critiques)
    critique_text = "\n\n".join(f"[{lbl}]\n{format_critique(c)}" for lbl, c in by_label.items())

    async def vote(model: str) -> Ballot | None:
        try:
            llm = build_reviewer(model, max_tokens, config).with_structured_output(Ballot).with_retry(stop_after_attempt=retries)
            return await llm.ainvoke([HumanMessage(content=VOTE_PROMPT.format(report=report[:20000], critiques=critique_text))])
        except Exception:
            return None

    ballots = [b for b in await asyncio.gather(*(vote(m) for m in critiques)) if b is not None]
    tally = weighted_borda(ballots, list(by_label))

    # 3. Deterministic citation check.
    flagged_urls = check_citations(report, notes)

    # 4. Revision with the report writer, feedback ordered by vote.
    feedback = "\n\n".join(f"[{lbl}, score {score:.2f}]\n{format_critique(by_label[lbl])}" for lbl, score in tally)
    if flagged_urls:
        feedback += "\n\n[Citation check]\nThese cited URLs do not appear in the research notes; remove or replace them:\n" + "\n".join(f"- {u}" for u in flagged_urls)
    writer = build_reviewer(configurable.final_report_model, configurable.final_report_model_max_tokens, config)
    try:
        revised = await writer.ainvoke([HumanMessage(content=REVISE_PROMPT.format(date=get_today_str(), notes=notes_for_prompt, report=report, feedback=feedback))])
        revised_text = revised.content if isinstance(revised.content, str) else str(revised.content)
    except Exception:
        revised_text = report

    scores = {label_to_model[lbl]: c.overall_score for lbl, c in by_label.items()}
    top_label = tally[0][0] if tally else None
    dissent = [
        f"{label_to_model[lbl]} scored the draft {c.overall_score}/10"
        for lbl, c in by_label.items()
        if abs(c.overall_score - (sum(scores.values()) / len(scores))) >= 3
    ]
    notes_items = [
        f"Reviewed by {len(critiques)} models from different vendors ({', '.join(critiques)}); critiques were anonymized before voting.",
        "Draft scores: " + ", ".join(f"{m} {s}/10" for m, s in scores.items()),
        f"Most useful critique (peer vote): {label_to_model[top_label]}" if top_label else "No ballots were returned.",
    ]
    if dissent:
        notes_items.append("Dissent: " + "; ".join(dissent))
    if flagged_urls:
        notes_items.append("Citations not found in research notes (flagged for removal): " + ", ".join(flagged_urls))
    if failed:
        notes_items.append("Reviewers that failed: " + ", ".join(failed))
    final = revised_text.rstrip() + "\n\n---\n\n## Review notes\n\n" + "\n".join(f"- {item}" for item in notes_items) + "\n"

    return {
        "final_report": final,
        "messages": [AIMessage(content=final)],
        "review": {
            "status": "ok",
            "reviewers": list(critiques),
            "failed": failed,
            "labels": label_to_model,
            "tally": tally,
            "ballots": len(ballots),
            "flagged_urls": flagged_urls,
            "scores": scores,
        },
    }
