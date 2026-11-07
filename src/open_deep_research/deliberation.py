"""Deliberation rounds between reviewers, with guards against sycophancy.

Optional step of the cross-vendor review (``REVIEW_DELIBERATION_ROUNDS``, 0 = off, at
most 3). In each round:

1. A **challenger** is assigned to every critique. The challenger rotates each round
   and is never the critique's author, so every finding is contested by a different
   model over successive rounds.
2. The challenger may contest specific findings, ideally with an exact quote from the
   research notes. Challenging nothing is allowed.
3. The **author** answers each challenge: MAINTAIN, REVISE (with corrected text) or
   WITHDRAW.
4. A change of position counts only when it is **grounded**: the challenger's or the
   author's quote must appear verbatim in the research notes (checked in code, not by
   a model). An ungrounded change is ignored, the original finding is kept, and the
   change is flagged as possible sycophancy.

Rounds stop early when no challenger contests anything. Everything that happened is
returned as a log for the Review notes, the run export and the comparison harness.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Literal

from pydantic import BaseModel, Field

from open_deep_research.cross_vendor_review import (
    FINDING_FIELDS,
    Critique,
    enumerate_findings,
    quote_in_notes,
)

MAX_ROUNDS = 3


class Challenge(BaseModel):
    """A challenger's objection to one finding."""

    finding_id: str = Field(description="Id of the challenged finding, e.g. 'C2-U1'.")
    objection: str = Field(description="Why the finding is wrong, overstated or unsupported by the notes.")
    evidence_quote: str = Field(default="", description="An EXACT quote from the research notes that settles the objection, if one exists.")


class ChallengeSet(BaseModel):
    """All challenges against one critique (may be empty)."""

    challenges: list[Challenge] = Field(default_factory=list)


class ChallengeResponse(BaseModel):
    """The author's answer to one challenge."""

    finding_id: str = Field(description="Id of the challenged finding.")
    stance: Literal["MAINTAIN", "REVISE", "WITHDRAW"] = Field(
        description="MAINTAIN: the finding stands. REVISE: replace it with revised_text. WITHDRAW: the finding was wrong."
    )
    revised_text: str = Field(default="", description="For REVISE: the corrected finding.")
    evidence_quote: str = Field(default="", description="An EXACT quote from the research notes that supports your answer.")
    reason: str = Field(default="", description="One sentence explaining the answer.")


class ResponseSet(BaseModel):
    """The author's answers to all challenges in a round."""

    responses: list[ChallengeResponse] = Field(default_factory=list)


CHALLENGE_PROMPT = """You are the challenger in round {round} of a review of a research report. Another reviewer wrote critique {label}. Contest only findings you believe are wrong, overstated or not supported by the research notes.

Research notes:
{notes}

Draft report:
{report}

Findings in critique {label} (id: finding):
{findings}

For each finding you contest, give the finding id, your objection and, when a passage in the notes settles it, an EXACT quote from the notes. Contesting nothing is a valid answer when the findings hold up. Do not contest a finding just to disagree, and do not invent quotes."""

RESPONSE_PROMPT = """Earlier you reviewed a research report. Another reviewer has challenged some of your findings. Answer each challenge.

Research notes:
{notes}

Challenges (id: your finding / objection / quote offered):
{challenges}

For each challenged finding choose one stance:
- MAINTAIN: the research notes still support your finding.
- REVISE: the finding was partly wrong; give the corrected finding in revised_text.
- WITHDRAW: the finding was wrong.
Change your position only if the research notes show you were wrong, and put the EXACT passage from the notes that changed your mind in evidence_quote. Do not change position because the challenger sounds confident or to be agreeable: a change without a passage from the notes is ignored and flagged."""


@dataclass
class DeliberationResult:
    """Outcome of all deliberation rounds."""

    critiques: dict[str, Critique]
    rounds_requested: int = 0
    rounds_run: int = 0
    log: list[dict[str, Any]] = field(default_factory=list)

    def counts(self) -> dict[str, int]:
        """Totals by outcome."""
        out = {"challenges": len(self.log), "held": 0, "changed_with_evidence": 0, "unsupported_changes": 0, "no_response": 0}
        for entry in self.log:
            out[entry["outcome"]] += 1
        return out

    def summary(self) -> dict[str, Any]:
        """Compact form for the review state."""
        return {"rounds_requested": self.rounds_requested, "rounds_run": self.rounds_run, **self.counts()}


def challenger_for(author: str, models: list[str], round_no: int) -> str:
    """Rotate challengers: round r uses the model r places after the author, never the author."""
    if author not in models or len(models) < 2:
        others = [m for m in models if m != author]
        return others[0] if others else author
    n = len(models)
    offset = (round_no - 1) % (n - 1) + 1  # 1..n-1, so never the author
    return models[(models.index(author) + offset) % n]


def apply_responses(
    critique: Critique,
    label: str,
    challenges: list[Challenge],
    responses: list[ChallengeResponse],
    notes: str,
) -> tuple[Critique, list[dict[str, Any]]]:
    """Apply grounded position changes; keep findings whose change is not grounded in the notes.

    Returns (updated critique, one log entry per challenge).
    """
    findings = enumerate_findings(critique, label)
    by_challenge = {c.finding_id: c for c in challenges if c.finding_id in findings}
    by_response = {r.finding_id: r for r in responses}
    replace: dict[str, str | None] = {}  # finding id -> new text, or None to remove
    log: list[dict[str, Any]] = []
    for fid, ch in by_challenge.items():
        resp = by_response.get(fid)
        entry = {"finding_id": fid, "finding": findings[fid], "objection": ch.objection}
        if resp is None:
            entry["outcome"] = "no_response"
        elif resp.stance == "MAINTAIN":
            entry["outcome"] = "held"
        else:
            grounded = quote_in_notes(ch.evidence_quote, notes) or quote_in_notes(resp.evidence_quote, notes)
            entry["stance"] = resp.stance
            if not grounded:
                entry["outcome"] = "unsupported_changes"
            elif resp.stance == "WITHDRAW":
                entry["outcome"] = "changed_with_evidence"
                replace[fid] = None
            elif resp.revised_text.strip():
                entry["outcome"] = "changed_with_evidence"
                entry["revised"] = resp.revised_text.strip()
                replace[fid] = resp.revised_text.strip()
            else:  # REVISE with nothing to revise to: keep as is
                entry["outcome"] = "held"
        log.append(entry)

    updated: dict[str, list[str]] = {}
    for code, attr in FINDING_FIELDS.items():
        kept: list[str] = []
        for i, text in enumerate(getattr(critique, attr), start=1):
            fid = f"{label}-{code}{i}"
            if fid not in replace:
                kept.append(text)
            elif replace[fid] is not None:
                kept.append(replace[fid])
        updated[attr] = kept
    return critique.model_copy(update=updated), log


Ask = Callable[[str, type[BaseModel], str], Awaitable[BaseModel]]
"""ask(model, schema, prompt) -> structured answer; raises on failure."""


async def deliberate(
    by_label: dict[str, Critique],
    label_to_model: dict[str, str],
    notes: str,
    report: str,
    rounds: int,
    ask: Ask,
) -> DeliberationResult:
    """Run up to ``rounds`` (capped at MAX_ROUNDS) challenge/response rounds."""
    rounds = max(0, min(int(rounds or 0), MAX_ROUNDS))
    result = DeliberationResult(critiques=dict(by_label), rounds_requested=rounds)
    models = list(dict.fromkeys(label_to_model.values()))
    if rounds == 0 or len(models) < 2:
        return result

    async def one(round_no: int, lbl: str, crit: Critique) -> tuple[str, Critique, list[dict[str, Any]]]:
        findings = enumerate_findings(crit, lbl)
        if not findings:
            return lbl, crit, []
        author = label_to_model[lbl]
        challenger = challenger_for(author, models, round_no)
        listing = "\n".join(f"{fid}: {text}" for fid, text in findings.items())
        try:
            cs = await ask(challenger, ChallengeSet, CHALLENGE_PROMPT.format(round=round_no, label=lbl, notes=notes, report=report[:20000], findings=listing))
            challenges = [c for c in cs.challenges if c.finding_id in findings]
        except Exception:
            return lbl, crit, []
        if not challenges:
            return lbl, crit, []
        text = "\n".join(f"{c.finding_id}: {findings[c.finding_id]} / {c.objection} / {c.evidence_quote or '(no quote)'}" for c in challenges)
        try:
            rs = await ask(author, ResponseSet, RESPONSE_PROMPT.format(notes=notes, challenges=text))
            responses = rs.responses
        except Exception:
            responses = []
        updated, log = apply_responses(crit, lbl, challenges, responses, notes)
        for entry in log:
            entry.update({"round": round_no, "challenger": challenger, "author": author})
        return lbl, updated, log

    for round_no in range(1, rounds + 1):
        outcomes = await asyncio.gather(*(one(round_no, lbl, c) for lbl, c in result.critiques.items()))
        round_log = [e for _, _, log in outcomes for e in log]
        for lbl, crit, _ in outcomes:
            result.critiques[lbl] = crit
        result.rounds_run = round_no
        result.log.extend(round_log)
        if not round_log:
            break
    return result


def notes_line(result: DeliberationResult) -> str:
    """One line for the report's Review notes."""
    c = result.counts()
    line = (
        f"Deliberation: {result.rounds_run} round(s) with rotating challengers; {c['challenges']} challenge(s): "
        f"{c['held']} finding(s) held, {c['changed_with_evidence']} changed with a passage from the notes"
    )
    if c["unsupported_changes"]:
        line += f", {c['unsupported_changes']} position change(s) without supporting evidence ignored (possible sycophancy)"
    if c["no_response"]:
        line += f", {c['no_response']} unanswered"
    return line + "."
