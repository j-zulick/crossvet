"""Tests for the blind first pass (offline)."""

import asyncio

import pytest

from open_deep_research import cross_vendor_review as rc
from open_deep_research.blind_pass import (
    BlindOutline,
    BlindPoint,
    add_omissions,
    assess,
    covered,
    notes_line,
    outline_all,
    reminder,
)
from open_deep_research.cross_vendor_review import Ballot, CriticReport, Critique

NOTES = (
    "The plant opened in March 2024 and employs 1,200 people according to the company filing. "
    "Regulators fined the operator 4.5 million dollars in 2025 for wastewater violations."
)
OPENED = BlindPoint(point="It opened in March 2024.", evidence_quote="The plant opened in March 2024")
FINE = BlindPoint(point="The operator was fined $4.5M in 2025.", evidence_quote="Regulators fined the operator 4.5 million dollars in 2025")
MADE_UP = BlindPoint(point="It is the largest in Europe.", evidence_quote="the largest plant in Europe by output")
DRAFT = "The plant opened in March 2024 and now employs about 1,200 people."


def test_coverage_needs_the_numbers_and_most_distinctive_words():
    assert covered(OPENED, DRAFT)
    assert not covered(FINE, DRAFT)
    assert not covered(BlindPoint(point="Opened in 2023", evidence_quote="The plant opened in March 2023"), DRAFT)
    assert covered(FINE, "In 2025 regulators fined the operator 4.5 million dollars over wastewater.")


def test_assess_grounds_dedupes_and_adds_omissions_to_the_right_critique():
    outlines = {"openai:a": [OPENED, FINE, MADE_UP], "anthropic:b": [FINE]}
    res = assess(outlines, NOTES, DRAFT)
    s = res.summary()
    assert (s["points"], s["covered"], s["omitted"], s["ungrounded"]) == (4, 1, 1, 1)
    assert res.omissions[0]["reviewer"] == "openai:a"
    crits = {"openai:a": Critique(overall_score=6), "anthropic:b": Critique(missing_perspectives=["x"], overall_score=7)}
    updated = add_omissions(crits, res)
    assert len(updated["openai:a"].missing_perspectives) == 1
    assert "fined the operator 4.5 million" in updated["openai:a"].missing_perspectives[0]
    assert updated["anthropic:b"].missing_perspectives == ["x"]
    line = notes_line(res)
    assert "1 grounded omission(s)" in line and "1 dropped because their passage is not in the notes" in line


def test_outline_failures_and_wrong_types_are_listed_not_fatal():
    async def ask(m):
        if m == "down":
            raise RuntimeError("provider down")
        if m == "odd":
            return Ballot(ranking=["C1"], confidence=0.5)
        return BlindOutline(points=[OPENED, FINE, MADE_UP])

    got, failed = asyncio.run(outline_all(["ok", "down", "odd"], ask, max_points=2))
    assert list(got) == ["ok"] and len(got["ok"]) == 2 and failed == ["down", "odd"]
    assert "- It opened in March 2024." in reminder(got["ok"]) and reminder([]) == ""


class Structured:
    def __init__(self, result):
        self.result = result

    def with_retry(self, **_):
        return self

    async def ainvoke(self, messages):
        Model.prompts.append(messages[0].content)
        return self.result


class Model:
    prompts: list[str] = []

    def __init__(self, name):
        self.name = name

    def with_structured_output(self, schema, **_):
        if schema is BlindOutline:
            return Structured(BlindOutline(points=[OPENED, FINE]))
        if schema is Critique:
            return Structured(Critique(unsupported_claims=[f"claim by {self.name}"], overall_score=6))
        if schema is CriticReport:
            return Structured(CriticReport(verdicts=[]))
        return Structured(Ballot(ranking=["C1", "C2"], confidence=0.8))

    async def ainvoke(self, _messages):
        class R:
            content = "REVISED"
        return R()


@pytest.fixture
def env(monkeypatch):
    monkeypatch.setenv("CROSS_VENDOR_REVIEW_ENABLED", "true")
    monkeypatch.setenv("REVIEW_MODELS", "openai:a,anthropic:b")
    monkeypatch.setenv("REVIEW_REVISER_MODEL", "google_genai:c")
    monkeypatch.setattr(rc, "build_reviewer", lambda m, t, c: Model(m))
    Model.prompts = []


def _state():
    return {"final_report": DRAFT, "raw_notes": [NOTES], "research_brief": "Tell me about the plant"}


def test_node_runs_blind_pass_before_critiques(env, monkeypatch, tmp_path):
    monkeypatch.setenv("REVIEW_BLIND_PASS_ENABLED", "true")
    monkeypatch.setenv("RUN_EXPORT_PATH", str(tmp_path / "runs.jsonl"))
    out = asyncio.run(rc.cross_vendor_review(_state(), {"configurable": {}}))
    blind = out["review"]["blind_pass"]
    assert (blind["reviewers"], blind["covered"], blind["omitted"]) == (2, 2, 1)
    blind_prompts = [p for p in Model.prompts if "Before you see anyone's report" in p]
    assert len(blind_prompts) == 2 and all(DRAFT not in p for p in blind_prompts)
    assert any("Before seeing the draft, you outlined" in p for p in Model.prompts)
    assert "Blind pass: 2 reviewer(s)" in out["final_report"]
    assert '"blind_pass"' in (tmp_path / "runs.jsonl").read_text()


def test_node_skips_blind_pass_by_default(env, monkeypatch):
    monkeypatch.delenv("REVIEW_BLIND_PASS_ENABLED", raising=False)
    out = asyncio.run(rc.cross_vendor_review(_state(), {"configurable": {}}))
    assert out["review"]["blind_pass"] is None
    assert not any("Before you see anyone's report" in p for p in Model.prompts)
