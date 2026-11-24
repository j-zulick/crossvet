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


# ---------------------------------------------------------------------------
# engagement labels, early stopping and the false-consensus guard
# ---------------------------------------------------------------------------
from open_deep_research.deliberation import (  # noqa: E402
    Assessment,
    StopPolicy,
    apply_engagement,
    decide_stop,
    round_stats,
)

SUPPORT = "The plant opened in March 2024"
EARLY = StopPolicy(early_stop=True, consensus_threshold=1.0, min_rounds=1, min_grounded_share=0.5)


def test_disagree_assessments_become_challenges_without_duplicates():
    cs = ChallengeSet(
        assessments=[
            Assessment(finding_id="C1-U1", verdict="DISAGREE", note="overstated", evidence_quote=QUOTE),
            Assessment(finding_id="C1-U2", verdict="AGREE"),
            Assessment(finding_id="C1-U3", verdict="DISAGREE", note="dup"),
        ],
        challenges=[Challenge(finding_id="C1-U3", objection="explicit wins")],
    )
    got = {c.finding_id: c.objection for c in cs.all_challenges()}
    assert got == {"C1-U3": "explicit wins", "C1-U1": "overstated"}


def test_build_on_applies_only_with_a_quote_from_the_notes():
    c = crit("Headcount is unsupported", "Opening date is unsupported", "Site is unclear")
    assessments = [
        Assessment(finding_id="C1-U1", verdict="BUILD_ON", note="the filing gives 1,200", evidence_quote=QUOTE),
        Assessment(finding_id="C1-U2", verdict="BUILD_ON", note="it opened in 2023", evidence_quote="opened in 2023 per a blog"),
        Assessment(finding_id="C1-U3", verdict="BUILD_ON", note="see filing", evidence_quote=QUOTE),
        Assessment(finding_id="C9-U1", verdict="AGREE"),
    ]
    updated, log = apply_engagement(c, "C1", assessments, NOTES, changed={"C1-U3"})
    assert updated.unsupported_claims == [
        "Headcount is unsupported Also: the filing gives 1,200",
        "Opening date is unsupported",
        "Site is unclear",
    ]
    assert [(e["finding_id"], e["applied"]) for e in log] == [("C1-U1", True), ("C1-U2", False), ("C1-U3", False)]


def test_decide_stop_rules():
    def st(round_no, findings=2, agree=0, grounded=0, challenges=0, moved=0, assessed=None):
        a = [{"verdict": "AGREE", "grounded": i < grounded} for i in range(agree)]
        a += [{"verdict": "DISAGREE"}] * challenges
        if assessed == 0:
            a = []
        log = [{"outcome": "changed_with_evidence"}] * moved + [{"outcome": "held"}] * (challenges - moved)
        return round_stats(round_no, findings, a, log)

    legacy = StopPolicy()
    assert decide_stop([st(1, challenges=1)], 3, legacy, False) == (None, False)
    assert decide_stop([st(1)], 3, legacy, False) == ("no_challenges", False)
    assert decide_stop([st(1, findings=0)], 3, EARLY, False) == ("no_findings", False)
    # consensus backed by the notes stops at once
    assert decide_stop([st(1, agree=2, grounded=2)], 3, EARLY, False) == ("consensus", False)
    # endorsements without passages: the guard buys one more round, then consensus is accepted
    assert decide_stop([st(1, agree=2, grounded=0)], 3, EARLY, False) == (None, True)
    assert decide_stop([st(1, agree=2), st(2, agree=2)], 3, EARLY, True) == ("consensus", False)
    # silence is not consensus: one guard round, then it stops without claiming agreement
    assert decide_stop([st(1, assessed=0)], 3, EARLY, False) == (None, True)
    assert decide_stop([st(1, assessed=0), st(2, assessed=0)], 3, EARLY, True) == ("no_challenges", False)
    # a finding moved: keep going; min_rounds respected; cap respected
    assert decide_stop([st(1, agree=1, grounded=1, challenges=1, moved=1)], 3, EARLY, False) == (None, False)
    assert decide_stop([st(1, agree=2, grounded=2)], 3, StopPolicy(early_stop=True, min_rounds=2), False) == (None, False)
    assert decide_stop([st(1, challenges=2)], 1, EARLY, False) == ("max_rounds", False)
    # contested but nothing moves for two rounds: stable
    assert decide_stop([st(1, challenges=2)], 3, EARLY, False) == (None, False)
    assert decide_stop([st(1, challenges=2), st(2, challenges=2)], 3, EARLY, False) == ("stable", False)
    # majority threshold
    assert decide_stop([st(1, findings=4, agree=3, grounded=3, challenges=1)], 3,
                       StopPolicy(early_stop=True, consensus_threshold=0.75), False) == ("consensus", False)


def _engaged_asker(verdict: str, quote: str = "", stance: str = "MAINTAIN"):
    calls = []

    async def ask(model, schema, prompt):
        calls.append((model, schema.__name__))
        if schema is ChallengeSet:
            ids = [line.split(":", 1)[0] for line in prompt.split("(id: finding):\n", 1)[1].split("\n\n", 1)[0].splitlines()]
            return ChallengeSet(assessments=[Assessment(finding_id=i, verdict=verdict, note="n", evidence_quote=quote) for i in ids])
        return ResponseSet(responses=[ChallengeResponse(finding_id=_first_id(prompt), stance=stance)])

    return ask, calls


THREE = {"C1": "openai:a", "C2": "anthropic:b", "C3": "google:c"}


def _three():
    return {"C1": crit("Headcount is unsupported"), "C2": crit("Opening date is unsupported"), "C3": crit("Site is unclear")}


def test_grounded_consensus_stops_after_one_round_and_saves_calls():
    ask, calls = _engaged_asker("AGREE", SUPPORT)
    res = asyncio.run(deliberate(_three(), THREE, NOTES, "report", 3, ask, EARLY))
    assert (res.rounds_run, res.stop_reason, res.rounds_saved, res.guard_rounds) == (1, "consensus", 2, 0)
    assert res.model_calls == len(calls) == 3  # one assessment per critique, no responses needed
    assert res.agreement_rate == 1.0
    line = notes_line(res)
    assert "Stopped after round 1 of 3" in line and "3 agree (3 citing the notes)" in line
    summary = res.summary()
    assert summary["stop_reason"] == "consensus" and summary["rounds_saved"] == 2 and summary["agree_grounded"] == 3


def test_ungrounded_consensus_triggers_the_guard_once():
    ask, _ = _engaged_asker("AGREE")
    res = asyncio.run(deliberate(_three(), THREE, NOTES, "report", 3, ask, EARLY))
    assert (res.rounds_run, res.stop_reason, res.guard_rounds) == (2, "consensus", 1)
    assert "not backed by the notes" in notes_line(res)


def test_stable_disagreement_stops_early_but_legacy_runs_to_the_cap():
    ask, _ = _engaged_asker("DISAGREE", stance="MAINTAIN")
    early = asyncio.run(deliberate(_three(), THREE, NOTES, "report", 3, ask, EARLY))
    assert (early.rounds_run, early.stop_reason) == (2, "stable")
    assert early.counts()["held"] == 6 and early.critiques == _three()
    legacy = asyncio.run(deliberate(_three(), THREE, NOTES, "report", 3, ask))
    assert (legacy.rounds_run, legacy.stop_reason) == (3, "max_rounds")
    assert early.model_calls < legacy.model_calls


def test_off_and_single_model_reasons():
    ask, _ = _engaged_asker("AGREE", SUPPORT)
    assert asyncio.run(deliberate(_three(), THREE, NOTES, "r", 0, ask, EARLY)).stop_reason == "off"
    assert asyncio.run(deliberate(_three(), {k: "openai:a" for k in THREE}, NOTES, "r", 2, ask, EARLY)).stop_reason == "single_model"
