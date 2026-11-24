"""The verdict line, the cost estimate before a run, and the offline demo."""

from __future__ import annotations

import io
from types import SimpleNamespace

import pytest

from open_deep_research import cli, demo, estimate
from open_deep_research.cross_vendor_review import verdict_line


def test_verdict_line_counts_problems_in_code():
    clean = verdict_line([], [], [], [], [], [])
    assert clean.startswith("**Verdict: no problems found by the checks.**") and "not proof" in clean
    line = verdict_line(["u1", "u2"], ["u3"], ["s1"], [{"finding": "f"}], ["d"], ["m"], "timeout")
    assert line.startswith("**Verdict: check before relying on it.**")
    for part in ("2 citation(s) not found", "1 cited URL(s) found only inside", "1 source(s) flagged", "1 finding(s) disputed",
                 "1 reviewer point(s) of dissent", "1 reviewer(s) failed", "1 revision failed"):
        assert part in line


def cfg(**over):
    base = dict(max_researcher_iterations=6, max_concurrent_research_units=5, max_react_tool_calls=10, allow_clarification=True,
                review_models="openai:a,anthropic:b,google:c", review_panel_limit=2, cross_vendor_review_enabled=True,
                review_blind_pass_enabled=True, review_deliberation_rounds=2, review_critic_enabled=True, review_reviser_model="",
                research_model="openai:r")
    base.update(over)
    ns = SimpleNamespace(**base)
    ns.model_for = lambda role: {"summarization": "openai:s", "compression": "openai:s", "final_report": "openai:w"}.get(role, ns.research_model)
    return ns


def test_stage_counts_follow_the_settings():
    by_name = {s.name: s for s in estimate.stages(cfg())}
    assert (by_name["supervisor"].calls_low, by_name["supervisor"].calls_high) == (1, 6)
    assert (by_name["researchers"].calls_low, by_name["researchers"].calls_high) == (6, 300)
    assert by_name["review: critiques and vote"].models == ["openai:a", "anthropic:b"]  # panel limit 2
    assert (by_name["review: deliberation"].calls_low, by_name["review: deliberation"].calls_high) == (2, 4)
    assert by_name["review: revision"].models == ["openai:w"]
    quick = {s.name for s in estimate.stages(cfg(cross_vendor_review_enabled=False, review_blind_pass_enabled=False))}
    assert not any(n.startswith("review") for n in quick)


def test_prices_and_rendering():
    prices = {m: (1e-6, 4e-6) for m in ("openai:r", "openai:s", "openai:w", "openai:a")}
    items = estimate.price_stages(estimate.stages(cfg()), prices)
    report = {s.name: s for s in items}["report"]
    assert report.cost_low == pytest.approx(30_000 * 1e-6 + 6_000 * 4e-6)
    review = {s.name: s for s in items}["review: critiques and vote"]
    assert review.cost_low is None and review.unpriced == ["anthropic:b"]
    text = estimate.render(items, "deep")
    assert "effort deep" in text and "no price known for: anthropic:b" in text and "Nov 17 pilot" in text and "total for priced stages" in text
    assert "no stage could be priced" in estimate.render(estimate.price_stages(estimate.stages(cfg()), {}))


def test_cli_estimate_calls_no_model(monkeypatch, capsys):
    monkeypatch.setattr(cli, "_run", lambda args: pytest.fail("a run was started"))
    monkeypatch.setattr(estimate, "_price", lambda model, prices: (1e-6, 2e-6))
    assert cli.main(["research", "What changed in EU AI rules this year?", "--estimate", "--effort", "quick"]) == 0
    out = capsys.readouterr().out
    assert "Rough estimate for one run (effort quick)" in out and "No model was called" in out


def test_demo_runs_offline():
    out = io.StringIO()
    assert demo.run(out) == 0
    text = out.getvalue()
    assert "hidden elements" in text and "override" in text and "code, slot strong" in text and "**Verdict:" in text
    assert "crossvet demo" in cli.START_HERE and "demo" in cli.TOOLS
