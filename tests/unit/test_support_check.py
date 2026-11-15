"""Tests for support checks (Jev) — offline: the real SDK against a mock HTTP transport."""

import asyncio
import json

import httpx2
import pytest
from typesafe_sdk import AsyncTypeSafeClient

from open_deep_research import cross_vendor_review as rc
from open_deep_research import doctor
from open_deep_research.blind_pass import BlindPoint, assess
from open_deep_research.cross_vendor_review import Critique
from open_deep_research.deliberation import (
    Assessment,
    Challenge,
    ChallengeResponse,
    StopPolicy,
    apply_engagement,
    apply_responses,
    deliberate,
    notes_line,
)
from open_deep_research.support_check import (
    JevChecker,
    build_checker,
    passes,
    score_pairs,
)

NOTES = "The plant opened in March 2024 and employs 1,200 people according to the company filing."
QUOTE = "employs 1,200 people according to the company filing"


def jev_transport(score_for, calls=None):
    """Mock TypeSafe API: answers the 'supported' Noul with score_for(claim, passage)."""

    def handler(req):
        body = json.loads(req.content)
        if calls is not None:
            calls.append(body)
        if score_for is None:
            return httpx2.Response(500, json={"error": "boom"})
        p = score_for(body["state"]["claim"], body["state"]["passage"])
        return httpx2.Response(200, json={"model": "jev-1.14.0", "usage": {"input_tokens": 40, "output_tokens": 0},
                                          "answers": {"supported": {"type": "noul", "noul": p}}})

    return httpx2.MockTransport(handler)


def checker(score_for, calls=None, **kw):
    client = AsyncTypeSafeClient(api_key="test", transport=jev_transport(score_for, calls))
    return JevChecker(model="jev-1.14.0", client=client, **kw)


def test_jev_checker_sends_one_noul_per_pair_and_reads_probabilities():
    calls = []
    c = checker(lambda claim, passage: 0.9 if "1,200" in claim else 0.1, calls)
    probs = asyncio.run(c.check([("It employs 1,200 people.", QUOTE), ("It employs 5,000 people.", QUOTE)]))
    assert probs == [0.9, 0.1] and c.errors == 0 and c.served_by == {"jev-1.14.0"}
    q = calls[0]["questions"]["supported"]
    assert calls[0]["model"] == "jev-1.14.0" and q["type"] == "noul" and set(q["criteria"]) == {"true", "false"}
    assert calls[0]["state"] == {"claim": "It employs 1,200 people.", "passage": QUOTE}


def test_failed_calls_give_none_and_never_block():
    c = checker(None)
    c_probs = asyncio.run(c.check([("x", "y")]))
    assert c_probs == [None] and c.errors == 1
    assert passes(None, 0.5) and passes(0.5, 0.5) and not passes(0.49, 0.5)


def test_score_pairs_deduplicates_and_is_empty_without_checker():
    calls = []
    c = checker(lambda *_: 0.7, calls)
    got = asyncio.run(score_pairs(c, [("a", "b"), ("a", "b"), ("c", "d")]))
    assert got == {("a", "b"): 0.7, ("c", "d"): 0.7} and len(calls) == 2
    assert asyncio.run(score_pairs(None, [("a", "b")])) == {}


def test_build_checker(monkeypatch):
    assert build_checker("") is None and build_checker("off") is None
    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="TYPESAFE_API_KEY"):
        build_checker("jev")
    monkeypatch.setenv("TYPESAFE_API_KEY", "k")
    monkeypatch.setenv("TYPESAFE_DEFAULT_MODEL", "jev-1.13.0")
    assert build_checker("jev").model == "jev-1.13.0" and build_checker("jev", "jev-1.14.0").model == "jev-1.14.0"
    with pytest.raises(ValueError):
        build_checker("other")


def crit(*claims):
    return Critique(unsupported_claims=list(claims), overall_score=6)


def test_a_real_quote_that_does_not_support_the_change_is_rejected():
    c = crit("Headcount is unsupported", "Date is unsupported")
    chs = [Challenge(finding_id="C1-U1", objection="the filing gives headcount", evidence_quote=QUOTE),
           Challenge(finding_id="C1-U2", objection="opening date is in the notes", evidence_quote=QUOTE)]
    rs = [ChallengeResponse(finding_id="C1-U1", stance="WITHDRAW", evidence_quote=QUOTE),
          ChallengeResponse(finding_id="C1-U2", stance="WITHDRAW", evidence_quote=QUOTE)]
    support = {("This is wrong or unsupported: the filing gives headcount", QUOTE): 0.92,
               ("This is wrong or unsupported: opening date is in the notes", QUOTE): 0.08}
    updated, log = apply_responses(c, "C1", chs, rs, NOTES, support, 0.5)
    assert updated.unsupported_claims == ["Date is unsupported"]
    by = {e["finding_id"]: e for e in log}
    assert by["C1-U1"]["outcome"] == "changed_with_evidence" and by["C1-U1"]["support"] == 0.92
    assert by["C1-U2"]["outcome"] == "unsupported_changes" and by["C1-U2"]["reason"].startswith("the passage does not support")


def test_low_support_ungrounds_agree_and_blocks_build_on():
    c = crit("Headcount is 1,200", "Opening date is March 2024")
    a = [Assessment(finding_id="C1-U1", verdict="AGREE", evidence_quote=QUOTE),
         Assessment(finding_id="C1-U2", verdict="BUILD_ON", note="per the filing", evidence_quote=QUOTE)]
    support = {("Headcount is 1,200", QUOTE): 0.9, ("Opening date is March 2024 per the filing", QUOTE): 0.1}
    updated, log = apply_engagement(c, "C1", a, NOTES, set(), support, 0.5)
    assert updated == c
    assert [(e["grounded"], e.get("applied")) for e in log] == [(True, None), (False, False)]


def test_deliberation_uses_the_checker_and_reports_it():
    calls = []
    jev = checker(lambda claim, passage: 0.05, calls)  # nothing is supported

    async def ask(model, schema, prompt):
        from open_deep_research.deliberation import ChallengeSet, ResponseSet

        if schema is ChallengeSet:
            fid = "C1-U1" if "critique C1" in prompt else "C2-U1"
            return ChallengeSet(assessments=[Assessment(finding_id=fid, verdict="DISAGREE", note="wrong", evidence_quote=QUOTE)])
        fid = "C1-U1" if "C1-U1" in prompt else "C2-U1"
        return ResponseSet(responses=[ChallengeResponse(finding_id=fid, stance="WITHDRAW", evidence_quote=QUOTE)])

    res = asyncio.run(deliberate({"C1": crit("a"), "C2": crit("b")}, {"C1": "openai:x", "C2": "anthropic:y"}, NOTES, "r", 1, ask,
                                 StopPolicy(early_stop=True), jev, 0.5))
    assert res.counts()["unsupported_changes"] == 2 and res.counts()["changed_with_evidence"] == 0
    assert res.summary()["support_checked"] == 2 and res.summary()["support_rejected"] == 2 and len(calls) == 2
    assert "Support check: 2 passage(s) scored, 2 rejected" in notes_line(res)


def test_blind_points_need_supporting_passages():
    pts = {"m": [BlindPoint(point="It opened in 2024.", evidence_quote="The plant opened in March 2024"),
                 BlindPoint(point="It employs 5,000.", evidence_quote=QUOTE)]}
    support = {("It opened in 2024.", "The plant opened in March 2024"): 0.95, ("It employs 5,000.", QUOTE): 0.02}
    s = assess(pts, NOTES, "unrelated draft", support, 0.5).summary()
    assert (s["unsupported"], s["omitted"]) == (1, 1)


def test_doctor_reports_jev_setup(monkeypatch):
    monkeypatch.setenv("REVIEW_SUPPORT_CHECKER", "jev")
    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
    msgs = [f for f in doctor.check() if f.message.startswith("support check")]
    assert msgs[0].level == "FAIL" and "TYPESAFE_API_KEY" in msgs[0].message
    monkeypatch.setenv("TYPESAFE_API_KEY", "k")
    msgs = [f for f in doctor.check() if f.message.startswith("support check")]
    assert msgs[0].level == "OK" and "--jev" in msgs[0].message


def test_doctor_live_jev_check(monkeypatch, capsys):
    monkeypatch.setenv("TYPESAFE_API_KEY", "k")
    real = JevChecker.__init__

    def init(self, model="", client=None, **kw):
        real(self, model=model, client=AsyncTypeSafeClient(api_key="k", transport=jev_transport(lambda c, p: 0.9 if "March" in c else 0.1)), **kw)

    monkeypatch.setattr(JevChecker, "__init__", init)
    assert doctor.jev_live_check() == 0
    out = capsys.readouterr().out
    assert "P(support)=0.90" in out and "Jev (jev-1.14.0): working" in out


def test_node_reports_checker_problems_without_failing(monkeypatch):
    monkeypatch.setenv("CROSS_VENDOR_REVIEW_ENABLED", "true")
    monkeypatch.setenv("REVIEW_MODELS", "openai:a,anthropic:b")
    monkeypatch.setenv("REVIEW_SUPPORT_CHECKER", "jev")
    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
    from tests.unit.test_blind_pass import Model

    monkeypatch.setattr(rc, "build_reviewer", lambda m, t, c: Model(m))
    out = asyncio.run(rc.cross_vendor_review({"final_report": "draft", "raw_notes": [NOTES], "research_brief": "b"}, {"configurable": {}}))
    assert out["review"]["status"] == "ok"
    assert out["review"]["support_check"]["error"].startswith("REVIEW_SUPPORT_CHECKER=jev needs TYPESAFE_API_KEY")
    assert "Support check off" in out["final_report"]
