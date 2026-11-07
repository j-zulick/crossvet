"""Tests for deliberation rounds and the sycophancy guard (offline)."""

import asyncio

from open_deep_research.cross_vendor_review import Critique
from open_deep_research.deliberation import (
    Challenge,
    ChallengeResponse,
    ChallengeSet,
    ResponseSet,
    apply_responses,
    challenger_for,
    deliberate,
    notes_line,
)

NOTES = "The plant opened in March 2024 and employs 1,200 people according to the company filing."
QUOTE = "employs 1,200 people according to the company filing"


def crit(*unsupported: str) -> Critique:
    return Critique(unsupported_claims=list(unsupported), overall_score=6)


def test_challenger_rotates_and_never_picks_author():
    models = ["a", "b", "c"]
    picks = [challenger_for("a", models, r) for r in (1, 2, 3, 4)]
    assert picks == ["b", "c", "b", "c"]
    assert all(challenger_for(m, models, r) != m for m in models for r in range(1, 6))
    assert challenger_for("a", ["a", "b"], 3) == "b"


def test_grounded_withdraw_removes_finding():
    c = crit("Headcount is unsupported", "Opening date is unsupported")
    ch = [Challenge(finding_id="C1-U1", objection="Notes give headcount", evidence_quote=QUOTE)]
    rs = [ChallengeResponse(finding_id="C1-U1", stance="WITHDRAW")]
    updated, log = apply_responses(c, "C1", ch, rs, NOTES)
    assert updated.unsupported_claims == ["Opening date is unsupported"]
    assert log[0]["outcome"] == "changed_with_evidence"


def test_ungrounded_change_is_ignored_and_flagged():
    c = crit("Headcount is unsupported")
    ch = [Challenge(finding_id="C1-U1", objection="I am confident it is fine")]
    rs = [ChallengeResponse(finding_id="C1-U1", stance="WITHDRAW", evidence_quote="a quote that is not in the notes at all")]
    updated, log = apply_responses(c, "C1", ch, rs, NOTES)
    assert updated.unsupported_claims == ["Headcount is unsupported"]
    assert log[0]["outcome"] == "unsupported_changes"


def test_revise_with_authors_own_quote_and_maintain():
    c = Critique(unsupported_claims=["Headcount is unsupported"], factual_concerns=["Date looks wrong"], overall_score=5)
    ch = [Challenge(finding_id="C2-U1", objection="partly wrong"), Challenge(finding_id="C2-F1", objection="date is right")]
    rs = [
        ChallengeResponse(finding_id="C2-U1", stance="REVISE", revised_text="Headcount needs a citation", evidence_quote=QUOTE),
        ChallengeResponse(finding_id="C2-F1", stance="MAINTAIN"),
    ]
    updated, log = apply_responses(c, "C2", ch, rs, NOTES)
    assert updated.unsupported_claims == ["Headcount needs a citation"]
    assert updated.factual_concerns == ["Date looks wrong"]
    assert [e["outcome"] for e in log] == ["changed_with_evidence", "held"]


def test_unknown_ids_and_missing_responses():
    c = crit("Headcount is unsupported")
    ch = [Challenge(finding_id="C9-U1", objection="not a real id"), Challenge(finding_id="C1-U1", objection="x")]
    updated, log = apply_responses(c, "C1", ch, [], NOTES)
    assert updated == c
    assert [(e["finding_id"], e["outcome"]) for e in log] == [("C1-U1", "no_response")]


def _asker(challenge_quote: str, stance: str = "WITHDRAW", fail: set[str] | None = None):
    calls = []

    async def ask(model, schema, prompt):
        calls.append((model, schema.__name__))
        if fail and model in fail:
            raise RuntimeError("provider down")
        if schema is ChallengeSet:
            label = prompt.split("critique ", 1)[1].split(".", 1)[0]
            return ChallengeSet(challenges=[Challenge(finding_id=f"{label}-U1", objection="see notes", evidence_quote=challenge_quote)])
        return ResponseSet(responses=[ChallengeResponse(finding_id=_first_id(prompt), stance=stance)])

    return ask, calls


def _first_id(prompt: str) -> str:
    line = prompt.split("Challenges (id: your finding / objection / quote offered):\n", 1)[1].splitlines()[0]
    return line.split(":", 1)[0]


def test_deliberate_rounds_stop_when_nothing_left_to_challenge():
    by_label = {"C1": crit("Headcount is unsupported"), "C2": crit("Opening date is unsupported")}
    ask, calls = _asker(QUOTE)
    res = asyncio.run(deliberate(by_label, {"C1": "openai:a", "C2": "anthropic:b"}, NOTES, "report", 3, ask))
    assert res.rounds_run == 2  # round 1 withdraws both findings; round 2 finds nothing to challenge
    assert res.counts()["changed_with_evidence"] == 2
    assert all(not c.unsupported_claims for c in res.critiques.values())
    assert ("openai:a", "ChallengeSet") in calls and ("anthropic:b", "ResponseSet") in calls
    assert "2 changed with a passage from the notes" in notes_line(res)


def test_deliberate_flags_sycophancy_and_caps_rounds():
    by_label = {"C1": crit("Headcount is unsupported"), "C2": crit("Opening date is unsupported")}
    ask, _ = _asker("", stance="WITHDRAW")
    res = asyncio.run(deliberate(by_label, {"C1": "openai:a", "C2": "anthropic:b"}, NOTES, "report", 9, ask))
    assert res.rounds_requested == 3 and res.rounds_run == 3
    assert res.counts()["unsupported_changes"] == 6
    assert res.critiques == by_label  # nothing changed without evidence
    assert "possible sycophancy" in notes_line(res)


def test_deliberate_off_and_failures():
    by_label = {"C1": crit("x is unsupported"), "C2": crit("y is unsupported")}
    labels = {"C1": "openai:a", "C2": "anthropic:b"}
    ask, calls = _asker(QUOTE)
    assert asyncio.run(deliberate(by_label, labels, NOTES, "r", 0, ask)).rounds_run == 0 and not calls
    ask, _ = _asker(QUOTE, fail={"openai:a", "anthropic:b"})
    res = asyncio.run(deliberate(by_label, labels, NOTES, "r", 2, ask))
    assert res.critiques == by_label and res.log == []
