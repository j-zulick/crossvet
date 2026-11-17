"""Tests for v1.5: context packs, follow-up questions, the Python API (offline)."""

import asyncio

import pytest
from langchain_core.messages import HumanMessage

from open_deep_research import api, cli, deep_agent, deep_researcher, doctor, followup
from open_deep_research.context import (
    PACKS,
    available_packs,
    context_block,
    with_context,
)
from tests.unit.test_deep_agent import agent_model  # noqa: F401  (fixture)
from tests.unit.test_end_to_end import REPORT, SOURCE_URL, scripted  # noqa: F401  (fixture)

# ---------------------------------------------------------------- context packs


def test_packs_and_block():
    assert available_packs() == ["marketing", "real-estate", "seo"]
    assert context_block() == ""
    block = context_block("SEO", "Consultant preparing a client audit")
    assert block.startswith("Requester's context:\nConsultant preparing a client audit")
    assert "Evidence rules for this field (SEO and generative engine optimization (GEO))" in block
    assert "Patents show what a search engine *could* do" in block
    for p in PACKS.values():
        assert p["title"] and p["guidance"].startswith("- ")
    with pytest.raises(ValueError, match="choose one of"):
        context_block("astrology")


def test_with_context_appends_once():
    brief = with_context("Research brief.", "marketing")
    assert brief.startswith("Research brief.\n\nEvidence rules") and with_context(brief, "marketing") == brief
    assert with_context("Brief.") == "Brief."


def test_pack_reaches_the_brief_supervisor_and_reviewers(scripted, monkeypatch):  # noqa: F811
    monkeypatch.setenv("CROSS_VENDOR_REVIEW_ENABLED", "true")
    monkeypatch.setenv("REVIEW_MODELS", "openai:a,anthropic:b")
    monkeypatch.setenv("REVIEW_REVISER_MODEL", "google_genai:c")
    monkeypatch.setenv("CONTEXT_PACK", "seo")
    monkeypatch.setenv("RESEARCH_CONTEXT", "Audit for a regional retailer")
    out = asyncio.run(deep_researcher.deep_researcher.ainvoke({"messages": [HumanMessage(content="Do AI Overviews cite top-ranking pages?")]}, {"configurable": {}}))
    brief = out["research_brief"]
    # the scripted model writes a fixed brief; the context is appended to whatever brief is written
    assert brief.index("Requester's context:\nAudit for a regional retailer") < brief.index("Evidence rules for this field (SEO")
    assert out["review"]["status"] == "ok"


def test_pack_reaches_the_deep_agent(agent_model, monkeypatch):  # noqa: F811
    from langchain_core.messages import AIMessage

    seen = []

    class FakeAgent:
        def with_config(self, _cfg):
            return self

        async def ainvoke(self, inp, _config=None):
            seen.extend(inp["messages"])
            return {"messages": [AIMessage(content="# Rents\n\nNo data.")]}

    monkeypatch.setattr(deep_agent, "build_agent", lambda model, tools, sub_model=None: FakeAgent())
    monkeypatch.setenv("CROSS_VENDOR_REVIEW_ENABLED", "false")
    monkeypatch.setenv("CONTEXT_PACK", "real-estate")
    asyncio.run(deep_agent.deep_agent.ainvoke({"messages": [HumanMessage(content="Median rents in Pittsburgh?")]}))
    assert seen[0].content == "Median rents in Pittsburgh?"
    assert "Markets are local" in seen[-1].content and seen[-1].content.startswith("Evidence rules for this field (Real estate)")


def test_doctor_checks_the_pack(monkeypatch):
    monkeypatch.setenv("CONTEXT_PACK", "seo")
    assert any(f.level == "OK" and "pack 'seo'" in f.message for f in doctor.check())
    monkeypatch.setenv("CONTEXT_PACK", "astrology")
    assert any(f.level == "FAIL" and "unknown CONTEXT_PACK" in f.message for f in doctor.check())


# ---------------------------------------------------------------- follow-ups

STATE = {
    "research_brief": "Solar additions in 2025",
    "raw_notes": [f"Solar additions grew strongly in 2025. Source: {SOURCE_URL}"],
    "final_report": REPORT,
}


def test_followup_answers_from_notes_and_flags_unread_urls():
    prompts = []

    async def ask(prompt):
        prompts.append(prompt)
        return f"Strong growth ([report]({SOURCE_URL})); see also [x](https://elsewhere.example/blog)."

    res = asyncio.run(followup.answer("  How fast did solar grow? ", STATE, ask))
    assert res["question"] == "How fast did solar grow?" and res["covered"] is True
    assert res["flagged_urls"] == ["https://elsewhere.example/blog"]
    assert "Use ONLY the research notes" in prompts[0] and SOURCE_URL in prompts[0]
    text = followup.render(res)
    assert text.startswith("## Follow-up: How fast did solar grow?") and "were not read during the research" in text


def test_followup_reports_when_the_notes_do_not_cover_it_and_needs_a_run():
    async def ask(prompt):
        return followup.NOT_COVERED + " New research on wind would be needed."

    assert asyncio.run(followup.answer("Wind?", STATE, ask))["covered"] is False
    with pytest.raises(ValueError, match="no report or research notes"):
        asyncio.run(followup.answer("Wind?", {}, ask))


def test_cli_ask_reads_the_thread_and_appends_to_file(monkeypatch, tmp_path, capsys):
    class Snap:
        values = STATE

    class Graph:
        async def aget_state(self, cfg):
            assert cfg == {"configurable": {"thread_id": "t1"}}
            return Snap()

    monkeypatch.setattr(cli, "_compile", lambda saver: Graph())
    monkeypatch.setenv("CROSSVET_CHECKPOINTS", str(tmp_path / "c.sqlite"))

    async def fake_ask(prompt):
        return f"Grew strongly ([r]({SOURCE_URL}))."

    monkeypatch.setattr(followup, "model_asker", lambda model, max_tokens, config=None: fake_ask)
    out = tmp_path / "followups.md"
    assert cli.main(["ask", "--thread", "t1", "How fast?", "--out", str(out)]) == 0
    assert out.read_text().startswith("## Follow-up: How fast?")
    assert cli.build_parser().parse_args(["ask", "--thread", "t", "q", "--model", "openai:m"]).model == "openai:m"


# ---------------------------------------------------------------- Python API


def test_api_run_and_ask(scripted, monkeypatch):  # noqa: F811
    monkeypatch.setenv("CROSS_VENDOR_REVIEW_ENABLED", "false")
    result = api.run("How much solar capacity was added in 2025?", config={"context_pack": "marketing"})
    assert result["final_report"] == REPORT and "Evidence rules for this field (Marketing" in result["research_brief"]

    async def fake_ask(prompt):
        return f"Strongly ([r]({SOURCE_URL}))."

    monkeypatch.setattr(followup, "model_asker", lambda model, max_tokens, config=None: fake_ask)
    assert api.ask("How fast?", result)["flagged_urls"] == []


def test_api_rejects_bad_input():
    with pytest.raises(ValueError, match="empty"):
        api.run("  ")
    with pytest.raises(ValueError, match="edition"):
        api.run("q", edition="other")
