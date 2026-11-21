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

Engagement (v1.1). The challenger labels **every** finding AGREE, DISAGREE or BUILD_ON,
referring to it by its anonymous id. DISAGREE is a challenge. BUILD_ON adds to a finding
and is applied only when its quote appears in the notes; otherwise it is ignored and
counted. AGREE may cite the passage that supports the finding.

Stopping (v1.1). With early stopping on, code decides after each round, with no model
call:

- **no findings**: nothing is left to review;
- **consensus**: no finding moved this round and the share of findings the challengers
  endorsed reaches ``consensus_threshold``. A **false-consensus guard** runs one more
  round (with the next challenger) when too few endorsements cite a passage that is in
  the notes, or when the challengers were silent;
- **stable**: two rounds in a row in which no finding moved, even though some were still
  contested; further rounds are unlikely to change anything.

With early stopping off, rounds stop only when no challenger contests anything (the v0.5
rule) or at the cap. Everything that happened is returned as a log for the Review notes,
the run export and the comparison harness.
"""

from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Literal

from pydantic import BaseModel, Field

from open_deep_research.cross_vendor_review import (
    FINDING_FIELDS,
    Critique,
    enumerate_findings,
    quote_in_notes,
)
from open_deep_research.support_check import SupportChecker, passes, score_pairs

MAX_ROUNDS = 3


class Challenge(BaseModel):
    """A challenger's objection to one finding."""

    finding_id: str = Field(description="Id of the challenged finding, e.g. 'C2-U1'.")
    objection: str = Field(description="Why the finding is wrong, overstated or unsupported by the notes.")
    evidence_quote: str = Field(default="", description="An EXACT quote from the research notes that settles the objection, if one exists.")


class Assessment(BaseModel):
    """A challenger's explicit position on one finding."""

    finding_id: str = Field(description="Id of the finding, e.g. 'C2-U1'.")
    verdict: Literal["AGREE", "DISAGREE", "BUILD_ON"] = Field(
        description="AGREE: the notes support the finding. DISAGREE: it is wrong, overstated or unsupported. BUILD_ON: it is right but incomplete; give the addition in note."
    )
    note: str = Field(default="", description="DISAGREE: the objection. BUILD_ON: what to add to the finding. AGREE: optional.")
    evidence_quote: str = Field(default="", description="An EXACT quote from the research notes that supports this verdict, if one exists.")
    fact: str = Field(default="", description="One sentence stating what the quoted passage itself says that this relies on: a statement about the subject, not about the report or the critique.")


class ChallengeSet(BaseModel):
    """A challenger's assessment of one critique: a verdict per finding (may be empty)."""

    assessments: list[Assessment] = Field(default_factory=list)
    challenges: list[Challenge] = Field(default_factory=list, description="Optional; DISAGREE assessments are challenges too.")

    def all_challenges(self) -> list[Challenge]:
        """Explicit challenges plus DISAGREE assessments, one per finding id."""
        out: dict[str, Challenge] = {c.finding_id: c for c in self.challenges}
        for a in self.assessments:
            if a.verdict == "DISAGREE" and a.finding_id not in out:
                out[a.finding_id] = Challenge(finding_id=a.finding_id, objection=a.note or "disagrees", evidence_quote=a.evidence_quote)
        return list(out.values())


class ChallengeResponse(BaseModel):
    """The author's answer to one challenge."""

    finding_id: str = Field(description="Id of the challenged finding.")
    stance: Literal["MAINTAIN", "REVISE", "WITHDRAW"] = Field(
        description="MAINTAIN: the finding stands. REVISE: replace it with revised_text. WITHDRAW: the finding was wrong."
    )
    revised_text: str = Field(default="", description="For REVISE: the corrected finding.")
    evidence_quote: str = Field(default="", description="An EXACT quote from the research notes that supports your answer.")
    fact: str = Field(default="", description="One sentence stating what the quoted passage itself says that this relies on: a statement about the subject, not about the report or the critique.")
    reason: str = Field(default="", description="One sentence explaining the answer.")


class ResponseSet(BaseModel):
    """The author's answers to all challenges in a round."""

    responses: list[ChallengeResponse] = Field(default_factory=list)


CHALLENGE_PROMPT = """You are the challenger in round {round} of a review of a research report. Another reviewer wrote critique {label}. Take an explicit position on every finding below, referring to it by its id.

Research notes:
{notes}

Draft report:
{report}

Findings in critique {label} (id: finding):
{findings}

For each finding give one assessment:
- AGREE: the research notes support the finding. Put the passage that supports it in evidence_quote when there is one.
- DISAGREE: the finding is wrong, overstated or not supported by the notes. Explain why in note and, when a passage settles it, put an EXACT quote from the notes in evidence_quote.
- BUILD_ON: the finding is right but incomplete. Put the addition in note and the EXACT passage from the notes that supports it in evidence_quote; an addition without a passage from the notes is ignored.
With every quote, state in fact, in one sentence, what the passage itself says that your verdict relies on (about the subject, not about the report), e.g. "The plant employs 1,200 people."
Do not disagree just to disagree, do not agree because a finding sounds plausible, and do not invent quotes."""

RESPONSE_PROMPT = """Earlier you reviewed a research report. Another reviewer has challenged some of your findings. Answer each challenge.

Research notes:
{notes}

Challenges (id: your finding / objection / quote offered):
{challenges}

For each challenged finding choose one stance:
- MAINTAIN: the research notes still support your finding.
- REVISE: the finding was partly wrong; give the corrected finding in revised_text.
- WITHDRAW: the finding was wrong.
Change your position only if the research notes show you were wrong, and put the EXACT passage from the notes that changed your mind in evidence_quote, and in fact one sentence stating what that passage says (about the subject, not about the report). Do not change position because the challenger sounds confident or to be agreeable: a change without a passage from the notes is ignored and flagged."""


@dataclass
class DeliberationResult:
    """Outcome of all deliberation rounds."""

    critiques: dict[str, Critique]
    rounds_requested: int = 0
    rounds_run: int = 0
    log: list[dict[str, Any]] = field(default_factory=list)
    engagement: list[dict[str, Any]] = field(default_factory=list)
    rounds: list[dict[str, Any]] = field(default_factory=list)
    stop_reason: str = ""
    guard_rounds: int = 0
    model_calls: int = 0

    def counts(self) -> dict[str, int]:
        """Totals by outcome."""
        out = {"challenges": len(self.log), "held": 0, "changed_with_evidence": 0, "unsupported_changes": 0, "no_response": 0}
        for entry in self.log:
            out[entry["outcome"]] += 1
        return out

    def engagement_counts(self) -> dict[str, int]:
        """Totals of the challengers' explicit verdicts."""
        out = {"agree": 0, "agree_grounded": 0, "disagree": 0, "build_on_applied": 0, "build_on_ignored": 0}
        for e in self.engagement:
            if e["verdict"] == "AGREE":
                out["agree"] += 1
                out["agree_grounded"] += int(bool(e.get("grounded")))
            elif e["verdict"] == "DISAGREE":
                out["disagree"] += 1
            elif e.get("applied"):
                out["build_on_applied"] += 1
            else:
                out["build_on_ignored"] += 1
        return out

    @property
    def rounds_saved(self) -> int:
        """Rounds requested but not needed."""
        return max(0, self.rounds_requested - self.rounds_run)

    @property
    def agreement_rate(self) -> float | None:
        """Share of findings endorsed in the last round that assessed any."""
        for r in reversed(self.rounds):
            if r["findings"]:
                return r["agreement_rate"]
        return None

    def summary(self) -> dict[str, Any]:
        """Compact form for the review state."""
        return {
            "rounds_requested": self.rounds_requested,
            "rounds_run": self.rounds_run,
            "rounds_saved": self.rounds_saved,
            "stop_reason": self.stop_reason,
            "guard_rounds": self.guard_rounds,
            "agreement_rate": self.agreement_rate,
            "model_calls": self.model_calls,
            **self.counts(),
            **self.engagement_counts(),
            **self.support_counts(),
        }

    def support_counts(self) -> dict[str, int]:
        """How many claims a support checker scored, and how many it rejected."""
        scored = [e for e in self.log + self.engagement if "support" in e]
        rejected = [e for e in scored if e.get("reason", "").startswith("the passage does not support")]
        return {"support_checked": len(scored), "support_rejected": len(rejected)}


@dataclass(frozen=True)
class StopPolicy:
    """When deliberation may stop before the round cap (decided in code, no model call).

    ``early_stop=False`` keeps the v0.5 rule: stop only when no challenger contests anything.
    """

    early_stop: bool = False
    consensus_threshold: float = 1.0
    min_rounds: int = 1
    min_grounded_share: float = 0.5


def round_stats(round_no: int, findings: int, assessments: list[dict[str, Any]], log: list[dict[str, Any]]) -> dict[str, Any]:
    """Per-round numbers the stop decision uses."""
    agree = [a for a in assessments if a["verdict"] == "AGREE"]
    moved = sum(1 for e in log if e["outcome"] == "changed_with_evidence") + sum(1 for a in assessments if a.get("applied"))
    return {
        "round": round_no,
        "findings": findings,
        "assessed": len(assessments),
        "agree": len(agree),
        "agree_grounded": sum(1 for a in agree if a.get("grounded")),
        "challenges": len(log),
        "moved": moved,
        "agreement_rate": round(len(agree) / findings, 3) if findings else 1.0,
    }


def decide_stop(stats: list[dict[str, Any]], rounds: int, policy: StopPolicy, guard_used: bool) -> tuple[str | None, bool]:
    """Return (stop reason or None to continue, whether the guard forced this continuation)."""
    cur = stats[-1]
    round_no = cur["round"]
    if cur["findings"] == 0:
        return "no_findings", False
    if not policy.early_stop:
        if cur["challenges"] == 0:
            return "no_challenges", False
        return ("max_rounds", False) if round_no >= rounds else (None, False)
    if round_no >= rounds:
        return "max_rounds", False
    if round_no < policy.min_rounds or cur["moved"]:
        return None, False
    if cur["agreement_rate"] >= policy.consensus_threshold or (cur["challenges"] == 0 and cur["assessed"] == 0):
        silent = cur["assessed"] == 0
        grounded_share = cur["agree_grounded"] / cur["agree"] if cur["agree"] else 0.0
        if not guard_used and (silent or grounded_share < policy.min_grounded_share):
            return None, True
        return ("no_challenges" if silent else "consensus"), False
    if len(stats) >= 2 and stats[-2]["moved"] == 0:
        return "stable", False
    return None, False


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
    support: dict[tuple[str, str], float | None] | None = None,
    min_support: float = 0.5,
) -> tuple[Critique, list[dict[str, Any]]]:
    """Apply grounded position changes; keep findings whose change is not grounded in the notes.

    With ``support`` (scores from a support checker, see ``support_check``), a change also
    needs its passage to support it: a low score turns it into an unsupported change.
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
            pair = change_pair(ch, resp, notes)
            prob = (support or {}).get(pair) if pair else None
            if prob is not None:
                entry["support"] = round(prob, 3)
                entry["support_pair"] = {"claim": pair[0][:500], "passage": pair[1][:800]}
            if grounded and not passes(prob, min_support):
                entry["outcome"] = "unsupported_changes"
                entry["reason"] = "the passage does not support the change"
            elif not grounded:
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


def apply_engagement(
    critique: Critique,
    label: str,
    assessments: list[Assessment],
    notes: str,
    changed: set[str],
    support: dict[tuple[str, str], float | None] | None = None,
    min_support: float = 0.5,
) -> tuple[Critique, list[dict[str, Any]]]:
    """Record AGREE / DISAGREE / BUILD_ON verdicts; apply BUILD_ON only with a quote found in the notes.

    ``changed`` holds finding ids already revised or withdrawn this round; additions to
    those are not applied. Returns (updated critique, one log entry per assessed finding).
    """
    findings = enumerate_findings(critique, label)
    additions: dict[str, str] = {}
    log: list[dict[str, Any]] = []
    for a in {a.finding_id: a for a in assessments if a.finding_id in findings}.values():
        grounded = quote_in_notes(a.evidence_quote, notes)
        entry: dict[str, Any] = {"finding_id": a.finding_id, "verdict": a.verdict, "grounded": grounded}
        pair = engagement_pair(a, findings[a.finding_id], notes)
        prob = (support or {}).get(pair) if pair else None
        if prob is not None:
            entry["support"] = round(prob, 3)
            entry["support_pair"] = {"claim": pair[0][:500], "passage": pair[1][:800]}
            if not passes(prob, min_support):
                entry["grounded"] = grounded = False
                entry["reason"] = "the passage does not support the verdict"
        if a.verdict == "BUILD_ON":
            ok = grounded and bool(a.note.strip()) and a.finding_id not in changed
            entry["applied"] = ok
            if ok:
                additions[a.finding_id] = a.note.strip()
                entry["addition"] = a.note.strip()
        log.append(entry)
    if not additions:
        return critique, log
    updated: dict[str, list[str]] = {}
    for code, attr in FINDING_FIELDS.items():
        updated[attr] = [
            f"{text} Also: {additions[f'{label}-{code}{i}']}" if f"{label}-{code}{i}" in additions else text
            for i, text in enumerate(getattr(critique, attr), start=1)
        ]
    return critique.model_copy(update=updated), log


def _claim_from_fact() -> bool:
    """REVIEW_SUPPORT_CLAIM=fact: put the reviewer's one-sentence fact to the support checker.

    The default (``finding``) puts the finding itself, which is usually a statement about the
    report ("the draft overstates X"), so a source passage can rarely state it directly. ``fact``
    asks instead whether the passage says what the reviewer relies on; it is weaker evidence that
    the verdict is right, so it is opt-in until measured (docs/EVALS.md).
    """
    return os.getenv("REVIEW_SUPPORT_CLAIM", "finding").strip().lower() == "fact"


def change_pair(ch: Challenge, resp: ChallengeResponse, notes: str) -> tuple[str, str] | None:
    """(claim, passage) behind a position change, or None when no quote is in the notes."""
    passage = next((q for q in (resp.evidence_quote, ch.evidence_quote) if quote_in_notes(q, notes)), "")
    if not passage or resp.stance == "MAINTAIN":
        return None
    if _claim_from_fact() and resp.fact.strip():
        return resp.fact.strip(), passage
    claim = resp.revised_text.strip() if resp.stance == "REVISE" else f"This is wrong or unsupported: {ch.objection}"
    return (claim, passage) if claim else None


def engagement_pair(a: Assessment, finding: str, notes: str) -> tuple[str, str] | None:
    """(claim, passage) behind an AGREE or BUILD_ON verdict, or None when its quote is not in the notes."""
    if a.verdict == "DISAGREE" or not quote_in_notes(a.evidence_quote, notes):
        return None
    if _claim_from_fact() and a.fact.strip():
        return a.fact.strip(), a.evidence_quote
    claim = finding if a.verdict == "AGREE" else f"{finding} {a.note.strip()}".strip()
    return claim, a.evidence_quote


Ask = Callable[[str, type[BaseModel], str], Awaitable[BaseModel]]
"""ask(model, schema, prompt) -> structured answer; raises on failure."""


async def deliberate(
    by_label: dict[str, Critique],
    label_to_model: dict[str, str],
    notes: str,
    report: str,
    rounds: int,
    ask: Ask,
    policy: StopPolicy | None = None,
    checker: SupportChecker | None = None,
    min_support: float = 0.5,
) -> DeliberationResult:
    """Run up to ``rounds`` (capped at MAX_ROUNDS) challenge/response rounds."""
    policy = policy or StopPolicy()
    rounds = max(0, min(int(rounds or 0), MAX_ROUNDS))
    result = DeliberationResult(critiques=dict(by_label), rounds_requested=rounds)
    models = list(dict.fromkeys(label_to_model.values()))
    if rounds == 0 or len(models) < 2:
        result.stop_reason = "off" if rounds == 0 else "single_model"
        return result

    async def counted(model: str, schema: type[BaseModel], prompt: str) -> BaseModel:
        result.model_calls += 1
        return await ask(model, schema, prompt)

    async def one(round_no: int, lbl: str, crit: Critique) -> tuple[str, Critique, list[dict[str, Any]], list[dict[str, Any]], int]:
        findings = enumerate_findings(crit, lbl)
        if not findings:
            return lbl, crit, [], [], 0
        author = label_to_model[lbl]
        challenger = challenger_for(author, models, round_no)
        listing = "\n".join(f"{fid}: {text}" for fid, text in findings.items())
        try:
            cs = await counted(challenger, ChallengeSet, CHALLENGE_PROMPT.format(round=round_no, label=lbl, notes=notes, report=report[:20000], findings=listing))
            assessments = [a for a in cs.assessments if a.finding_id in findings]
            challenges = [c for c in cs.all_challenges() if c.finding_id in findings]
        except Exception:
            return lbl, crit, [], [], len(findings)
        updated, log = crit, []
        if challenges:
            text = "\n".join(f"{c.finding_id}: {findings[c.finding_id]} / {c.objection} / {c.evidence_quote or '(no quote)'}" for c in challenges)
            try:
                rs = await counted(author, ResponseSet, RESPONSE_PROMPT.format(notes=notes, challenges=text))
                responses = rs.responses
            except Exception:
                responses = []
            by_resp = {r.finding_id: r for r in responses}
            pairs = [p for c in challenges if (r := by_resp.get(c.finding_id)) and (p := change_pair(c, r, notes))]
            support = await score_pairs(checker, pairs)
            updated, log = apply_responses(crit, lbl, challenges, responses, notes, support, min_support)
        changed = {e["finding_id"] for e in log if e["outcome"] == "changed_with_evidence"}
        pairs = [p for a in assessments if (p := engagement_pair(a, findings[a.finding_id], notes))]
        support = await score_pairs(checker, pairs)
        updated, engagement = apply_engagement(updated, lbl, assessments, notes, changed, support, min_support)
        for entry in log + engagement:
            entry.update({"round": round_no, "challenger": challenger, "author": author})
        return lbl, updated, log, engagement, len(findings)

    guard_used = False
    for round_no in range(1, rounds + 1):
        outcomes = await asyncio.gather(*(one(round_no, lbl, c) for lbl, c in result.critiques.items()))
        round_log = [e for _, _, log, _, _ in outcomes for e in log]
        round_eng = [e for _, _, _, eng, _ in outcomes for e in eng]
        for lbl, crit, _, _, _ in outcomes:
            result.critiques[lbl] = crit
        result.rounds_run = round_no
        result.log.extend(round_log)
        result.engagement.extend(round_eng)
        result.rounds.append(round_stats(round_no, sum(n for *_, n in outcomes), round_eng, round_log))
        reason, guard = decide_stop(result.rounds, rounds, policy, guard_used)
        if guard:
            guard_used = True
            result.guard_rounds += 1
        if reason:
            result.stop_reason = reason
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
    e = result.engagement_counts()
    if result.engagement:
        line += (f". Challenger verdicts: {e['agree']} agree ({e['agree_grounded']} citing the notes), {e['disagree']} disagree, "
                 f"{e['build_on_applied']} build-on applied")
        if e["build_on_ignored"]:
            line += f", {e['build_on_ignored']} build-on ignored (no passage from the notes)"
    sc = result.support_counts()
    if sc["support_checked"]:
        line += f". Support check: {sc['support_checked']} passage(s) scored, {sc['support_rejected']} rejected as not supporting their claim"
    reason = STOP_REASONS.get(result.stop_reason, "").format(rate=result.agreement_rate or 0)
    if reason and result.rounds_saved:
        line += f". Stopped after round {result.rounds_run} of {result.rounds_requested}: {reason}"
    if result.guard_rounds:
        line += "; one extra round was run because the agreement was not backed by the notes"
    return line + "."


STOP_REASONS = {
    "no_findings": "no findings left to review",
    "no_challenges": "no challenger contested anything",
    "consensus": "challengers endorsed {rate:.0%} of the findings and none moved",
    "stable": "no finding moved in two consecutive rounds",
}
