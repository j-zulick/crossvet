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
import json
import os
import random
import re
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any, Literal
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from langchain.chat_models import init_chat_model
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.runnables import RunnableConfig
from pydantic import BaseModel, Field

from open_deep_research.configuration import Configuration
from open_deep_research.utils import (
    get_api_key_for_model,
    get_today_str,
    structured_output_kwargs,
)

URL_RE = re.compile(r"https?://[^\s\)\]>\"']+")


def strip_tracking(text: str) -> str:
    """Remove utm_* tracking parameters (e.g. OpenAI's utm_source=openai) from every URL."""

    def clean(match: re.Match) -> str:
        url = match.group(0)
        trail = ""
        while url and url[-1] in ".,;:":
            trail, url = url[-1] + trail, url[:-1]
        parts = urlsplit(url)
        if "utm_" not in parts.query:
            return match.group(0)
        query = urlencode([(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True) if not k.lower().startswith("utm_")])
        return urlunsplit((parts.scheme, parts.netloc, parts.path, query, parts.fragment)) + trail

    return URL_RE.sub(clean, text or "")


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


class CriticVerdict(BaseModel):
    """The critic's verdict on one reviewer finding."""

    finding_id: str = Field(description="Id of the finding being judged, e.g. 'C2-U1'.")
    verdict: Literal["AGREE", "DISAGREE_EVIDENCE", "DISAGREE_CONCERN"] = Field(
        description="AGREE: the finding is correct and supported. DISAGREE_EVIDENCE: a passage in the research notes contradicts it (quote it). DISAGREE_CONCERN: the finding is speculative or unsupported, but no passage settles it."
    )
    evidence_quote: str = Field(default="", description="For DISAGREE_EVIDENCE: an exact quote from the research notes that contradicts the finding.")
    reason: str = Field(default="", description="One sentence explaining the verdict.")


class CriticReport(BaseModel):
    """All of the critic's verdicts for one critique."""

    verdicts: list[CriticVerdict] = Field(default_factory=list)


###################
# Pure helpers (unit-tested)
###################
def vendor_of(model: str) -> str:
    """Return the vendor behind a model string.

    ``openai:gpt-x`` -> ``openai``; ``openrouter:anthropic/claude`` -> ``anthropic``;
    ``ollama:x`` / ``local:x`` -> ``self-hosted``; a bare name -> the name itself.
    """
    model = (model or "").strip()
    provider, _, rest = model.partition(":")
    if not rest:
        return provider.lower()
    if provider == "openrouter":
        return rest.split("/", 1)[0].lower()
    if provider in ("ollama", "local"):
        return "self-hosted"
    if provider in ("google_genai", "google_vertexai", "google"):
        return "google"
    return provider.lower()


def reviser_conflicts(reviser: str, reviewers: list[str]) -> list[str]:
    """Reviewers that share a vendor with the reviser (empty means the reviser is independent)."""
    v = vendor_of(reviser)
    return [r for r in reviewers if vendor_of(r) == v]


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
        # Compare URLs the way a reader would: ignore scheme, "www.", fragments, trailing
        # slashes and tracking parameters (search tools add e.g. utm_source=openai).
        u = u.rstrip(".,;:)")
        parts = urlsplit(u)
        query = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True) if not k.lower().startswith("utm_")]
        host = parts.netloc.lower().removeprefix("www.")
        path = parts.path.rstrip("/")
        q = urlencode(query)
        return f"{host}{path}" + (f"?{q}" if q else "")

    known = {norm(u) for u in URL_RE.findall(research_text or "")}
    flagged: list[str] = []
    for u in URL_RE.findall(report or ""):
        u = u.rstrip(".,;:)")
        if norm(u) not in known and u not in flagged:
            flagged.append(u)
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


FINDING_FIELDS = {"U": "unsupported_claims", "F": "factual_concerns"}


def enumerate_findings(critique: Critique, label: str) -> dict[str, str]:
    """Give every checkable finding (unsupported claims, factual concerns) a stable id."""
    out: dict[str, str] = {}
    for code, attr in FINDING_FIELDS.items():
        for i, text in enumerate(getattr(critique, attr), start=1):
            out[f"{label}-{code}{i}"] = text
    return out


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "")).strip().lower()


def quote_in_notes(quote: str, notes: str, min_len: int = 12) -> bool:
    """Check that a quote of meaningful length appears verbatim (ignoring case and whitespace) in the notes."""
    q = _norm(quote)
    return len(q) >= min_len and q in _norm(notes)


def apply_verdicts(
    critique: Critique, label: str, verdicts: list[CriticVerdict], notes: str
) -> tuple[Critique, list[dict[str, str]], list[dict[str, str]]]:
    """Filter a critique's findings by critic verdicts.

    AGREE (or no verdict) keeps a finding. DISAGREE_EVIDENCE drops it only when the quoted
    passage really appears in the research notes; otherwise it is treated as a concern.
    DISAGREE_CONCERN moves the finding to the disputed list. Returns (kept critique,
    disputed, dropped).
    """
    by_id = {v.finding_id: v for v in verdicts}
    kept: dict[str, list[str]] = {attr: [] for attr in FINDING_FIELDS.values()}
    disputed: list[dict[str, str]] = []
    dropped: list[dict[str, str]] = []
    for code, attr in FINDING_FIELDS.items():
        for i, text in enumerate(getattr(critique, attr), start=1):
            fid = f"{label}-{code}{i}"
            v = by_id.get(fid)
            if v is None or v.verdict == "AGREE":
                kept[attr].append(text)
            elif v.verdict == "DISAGREE_EVIDENCE" and quote_in_notes(v.evidence_quote, notes):
                dropped.append({"id": fid, "finding": text, "evidence": v.evidence_quote, "reason": v.reason})
            else:
                disputed.append({"id": fid, "finding": text, "objection": v.reason or "critic could not verify"})
    return critique.model_copy(update=kept), disputed, dropped


def critic_for(author: str, models: list[str]) -> str:
    """Pick a critic from a different vendor/model than the critique's author (next in list)."""
    others = [m for m in models if m != author]
    if not others:
        return author
    idx = models.index(author) if author in models else -1
    return models[(idx + 1) % len(models)] if models[(idx + 1) % len(models)] != author else others[0]


def export_run(path: str, record: dict[str, Any]) -> None:
    """Append one run record as a JSON line (opt-in via RUN_EXPORT_PATH)."""
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")


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

Review the draft strictly against the research notes. Flag claims the notes do not support, statements that look wrong or overstated, and important missing perspectives. Suggest concrete revisions. Be specific and brief.
Give your own assessment: do not defer to how confident or polished the draft sounds, and do not soften a concern unless the notes resolve it."""

VOTE_PROMPT = """Several anonymous reviewers critiqued the same research report. Rank their critiques from most to least useful for improving the report's accuracy and completeness. Judge only the critiques' content: reward specific, evidence-based points over confident or agreeable wording, and do not rank a critique higher because others make the same point.

Draft report (for context):
{report}

Critiques:
{critiques}

Return every critique id exactly once in your ranking."""

CRITIC_PROMPT = """You are an independent critic auditing another reviewer's findings about a research report. Judge each finding ONLY against the research notes below.

Research notes:
{notes}

Draft report:
{report}

Findings to judge (id: finding):
{findings}

For every finding id return exactly one verdict:
- AGREE: the finding is correct and the notes support it.
- DISAGREE_EVIDENCE: a passage in the notes contradicts the finding. Put an EXACT quote from the notes in evidence_quote.
- DISAGREE_CONCERN: the finding is speculative, over-stated or unsupported, but no passage settles it.
Do not invent quotes. Do not add new findings.
Hold an evidence-based position: do not AGREE because a finding sounds plausible, is confidently worded or was raised by several reviewers, and do not disagree without a reason grounded in the notes."""

REVISE_PROMPT = """Revise the research report below using the reviewer feedback, which is listed in order of peer-voted usefulness. Today is {date}.

Rules:
- Only keep claims supported by the research notes; remove or qualify unsupported ones.
- Write for the reader of the final report. Do not mention the draft, the reviewers, the feedback, "the notes", "the supplied research" or what you removed or changed; simply leave out what is unsupported. Where a fact is genuinely uncertain or disputed, say so in plain language as part of the explanation.
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
    """LangGraph node: critique → critic check → anonymized vote → citation check → revision."""
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
            llm = build_reviewer(model, max_tokens, config).with_structured_output(Critique, **structured_output_kwargs(model)).with_retry(stop_after_attempt=retries)
            prompt = CRITIQUE_PROMPT.format(date=get_today_str(), brief=brief, notes=notes_for_prompt, report=report)
            return model, await llm.ainvoke([HumanMessage(content=prompt)])
        except Exception:
            return model, None

    results = await asyncio.gather(*(critique(m) for m in models))
    critiques = {m: c for m, c in results if c is not None}
    failed = [m for m, c in results if c is None]
    if len(critiques) < 2:
        return {"review": {"status": "skipped_no_quorum", "reviewers": models, "failed": failed}}

    # 2. Anonymize and shuffle, then let an independent critic check findings against the notes.
    by_label, label_to_model = anonymize(critiques)
    disputed: list[dict[str, str]] = []
    dropped: list[dict[str, str]] = []
    critic_status = "disabled"
    if configurable.review_critic_enabled:
        reviewer_models = list(critiques)

        async def run_critic(lbl: str, crit: Critique) -> tuple[str, list[CriticVerdict] | None]:
            findings = enumerate_findings(crit, lbl)
            if not findings:
                return lbl, []
            critic_model = critic_for(label_to_model[lbl], reviewer_models)
            try:
                llm = build_reviewer(critic_model, max_tokens, config).with_structured_output(CriticReport, **structured_output_kwargs(critic_model)).with_retry(stop_after_attempt=retries)
                listing = "\n".join(f"{fid}: {text}" for fid, text in findings.items())
                result = await llm.ainvoke([HumanMessage(content=CRITIC_PROMPT.format(notes=notes_for_prompt, report=report[:20000], findings=listing))])
                return lbl, result.verdicts
            except Exception:
                return lbl, None

        critic_results = await asyncio.gather(*(run_critic(lbl, c) for lbl, c in by_label.items()))
        unavailable = 0
        for lbl, verdicts in critic_results:
            if verdicts is None:
                unavailable += 1
                continue
            kept, d, x = apply_verdicts(by_label[lbl], lbl, verdicts, notes)
            by_label[lbl] = kept
            disputed.extend(d)
            dropped.extend(x)
        critic_status = "ok" if unavailable == 0 else f"partial ({unavailable} critic call(s) failed; those findings kept unchecked)"

    # 3. Anonymized vote by every successful reviewer over the checked critiques.
    critique_text = "\n\n".join(f"[{lbl}]\n{format_critique(c)}" for lbl, c in by_label.items())

    async def vote(model: str) -> Ballot | None:
        try:
            llm = build_reviewer(model, max_tokens, config).with_structured_output(Ballot, **structured_output_kwargs(model)).with_retry(stop_after_attempt=retries)
            return await llm.ainvoke([HumanMessage(content=VOTE_PROMPT.format(report=report[:20000], critiques=critique_text))])
        except Exception:
            return None

    ballots = [b for b in await asyncio.gather(*(vote(m) for m in critiques)) if b is not None]
    tally = weighted_borda(ballots, list(by_label))

    # 4. Deterministic citation check.
    flagged_urls = check_citations(report, notes)

    # 5. Revision with the report writer, feedback ordered by vote.
    feedback = "\n\n".join(f"[{lbl}, score {score:.2f}]\n{format_critique(by_label[lbl])}" for lbl, score in tally)
    if flagged_urls:
        feedback += "\n\n[Citation check]\nThese cited URLs do not appear in the research notes; remove or replace them:\n" + "\n".join(f"- {u}" for u in flagged_urls)
    reviser_model = configurable.review_reviser_model or configurable.final_report_model
    same_vendor = reviser_conflicts(reviser_model, list(critiques))
    revision_error = ""
    try:
        writer = build_reviewer(reviser_model, configurable.final_report_model_max_tokens, config)
        revised = await writer.ainvoke([HumanMessage(content=REVISE_PROMPT.format(date=get_today_str(), notes=notes_for_prompt, report=report, feedback=feedback))])
        revised_text = revised.content if isinstance(revised.content, str) else str(revised.content)
    except Exception as exc:  # keep the draft and say so in the Review notes
        revised_text = report
        revision_error = type(exc).__name__

    scores = {label_to_model[lbl]: c.overall_score for lbl, c in by_label.items()}
    top_label = tally[0][0] if tally else None
    dissent = [
        f"{label_to_model[lbl]} scored the draft {c.overall_score}/10"
        for lbl, c in by_label.items()
        if abs(c.overall_score - (sum(scores.values()) / len(scores))) >= 3
    ]
    notes_items = [
        f"Reviewed by {len(critiques)} models from {len({vendor_of(m) for m in critiques})} vendor(s) ({', '.join(critiques)}); critiques were anonymized before voting.",
        "Draft scores: " + ", ".join(f"{m} {s}/10" for m, s in scores.items()),
        f"Most useful critique (peer vote): {label_to_model[top_label]}" if top_label else "No ballots were returned.",
    ]
    if dissent:
        notes_items.append("Dissent: " + "; ".join(dissent))
    if flagged_urls:
        notes_items.append("Citations not found in research notes (flagged for removal): " + ", ".join(flagged_urls))
    if configurable.review_critic_enabled:
        notes_items.append(f"Independent critic: {critic_status}; {len(dropped)} finding(s) dropped as contradicted by the notes, {len(disputed)} disputed.")
    if same_vendor:
        notes_items.append(
            f"Warning: the reviser ({reviser_model}) shares a vendor with reviewer(s) {', '.join(same_vendor)}; "
            "set REVIEW_REVISER_MODEL to a model from another vendor for a fully independent revision."
        )
    if revision_error:
        notes_items.append(f"Revision by {reviser_model} failed ({revision_error}); the draft is shown unrevised, with the review above for a human to apply.")
    if failed:
        notes_items.append("Reviewers that failed: " + ", ".join(failed))
    final = revised_text.rstrip() + "\n\n---\n\n## Review notes\n\n" + "\n".join(f"- {item}" for item in notes_items) + "\n"
    if disputed:
        final += "\n### Disputed\n\nReviewer findings the critic could not confirm from the research notes; they need a human check.\n\n"
        final += "\n".join(f"- {d['finding']} — *{d['objection']}*" for d in disputed) + "\n"

    if configurable.run_export_path:
        try:
            export_run(configurable.run_export_path, {
                "exported_at": datetime.now(timezone.utc).isoformat(),
                "research_brief": brief,
                "draft_report": report,
                "revised_report": revised_text,
                "critiques": {label_to_model[lbl]: c.model_dump() for lbl, c in by_label.items()},
                "critic": {"status": critic_status, "dropped": dropped, "disputed": disputed},
                "ballots": [b.model_dump() for b in ballots],
                "tally": tally,
                "flagged_urls": flagged_urls,
                "failed_reviewers": failed,
            })
        except OSError:
            pass  # export is best-effort and must never break a run

    return {
        "final_report": strip_tracking(final),
        "messages": [AIMessage(content=final)],
        "review": {
            "status": "ok",
            "reviewers": list(critiques),
            "failed": failed,
            "reviser": reviser_model,
            "reviser_shares_vendor_with": same_vendor,
            "labels": label_to_model,
            "tally": tally,
            "ballots": len(ballots),
            "flagged_urls": flagged_urls,
            "scores": scores,
            "critic": {"status": critic_status, "dropped": len(dropped), "disputed": disputed},
        },
    }
