"""Routing from judged scores: cheapest within a margin, a confidence gate, exploration, automatic changes, the week."""

from __future__ import annotations

import json
import random
import time

import pytest

from crossvet import care, cli, routing, tuning

QUICK = "What is the ZIP code of 707 S Washington Blvd, Sarasota?"
SLOTS = {"quick": ["anthropic:claude-haiku-5-5", "openai:gpt-6-luna"], "strong": ["anthropic:claude-opus-5-5", "openai:gpt-6.1-sol"]}


@pytest.fixture(autouse=True)
def _keys(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "x")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "x")


class Fixed:
    def __init__(self, value: float) -> None:
        self.value = value

    def random(self) -> float:
        return self.value


def board(**cells):
    return {"quick": {m: {"n": n, "score": s, "low": low, "cost": 0.0} for m, (n, s, low) in cells.items()}}


def seed_scores(cv, model, kind, scores):
    for value in scores:
        turn = cv.store.add_turn("t", "api", "assistant", "x", model=model, cost=0.0)
        cv.lab.add_score(turn, model, kind, "judge", value, True, "", 0.0)


def test_the_cheapest_within_the_margin_of_the_best_goes_first(make):
    cfg = make(slots=SLOTS, router={"use": "scores", "min_scores": 5}).config
    b = board(**{"anthropic:claude-opus-5-5": (30, 4.8, 4.7), "openai:gpt-6-luna": (30, 4.6, 4.5), "openai:gpt-6.1-sol": (30, 4.0, 3.9)})
    ranked, why = routing.from_scores(cfg, "quick", b, True, Fixed(1.0))
    assert ranked[0] == "openai:gpt-6-luna" and "cheapest within 0.3" in why
    assert ranked.index("anthropic:claude-opus-5-5") < ranked.index("openai:gpt-6.1-sol")


def test_too_few_scores_or_an_untrusted_judge_leave_it_to_the_rules(make):
    cfg = make(slots=SLOTS, router={"use": "scores"}).config
    few = board(**{"openai:gpt-6-luna": (4, 5.0, 4.0)})
    assert routing.from_scores(cfg, "quick", few, True)[0] == []
    assert "20 judged answers" in routing.from_scores(cfg, "quick", few, True)[1]
    assert "disagrees" in routing.from_scores(cfg, "quick", board(**{"openai:gpt-6-luna": (40, 5, 5)}), False)[1]


def test_exploration_tries_the_second_choice(make):
    cfg = make(slots=SLOTS, router={"use": "scores", "min_scores": 5, "explore": 0.1}).config
    b = board(**{"anthropic:claude-opus-5-5": (30, 4.8, 4.7), "openai:gpt-6-luna": (30, 4.6, 4.5)})
    ranked, why = routing.from_scores(cfg, "quick", b, True, Fixed(0.05))
    assert ranked[0] == "anthropic:claude-opus-5-5" and why.startswith("exploring")
    picks = [routing.from_scores(cfg, "quick", b, True, random.Random(i))[0][0] for i in range(400)]
    assert 0.05 < picks.count("anthropic:claude-opus-5-5") / 400 < 0.16


def test_auto_routes_from_your_judged_answers(make):
    cv = make(slots=SLOTS, router={"use": "scores", "min_scores": 5, "explore": 0})
    assert "rules decide (no model has 5 judged answers" in cv.decide("auto", [{"role": "user", "content": QUICK}]).reason
    seed_scores(cv, "openai:gpt-6-luna", "quick", [5, 5, 4, 5, 5, 5])
    seed_scores(cv, "anthropic:claude-haiku-5-5", "quick", [3, 2, 3, 3, 2, 3])
    cv._score_cache = None
    decision = cv.decide("auto", [{"role": "user", "content": QUICK}])
    assert decision.model == "openai:gpt-6-luna" and "scores:" in decision.reason
    assert decision.ladder[:2] == ["openai:gpt-6-luna", "anthropic:claude-haiku-5-5"]


def test_your_accepted_route_beats_scores(make):
    cv = make(slots=SLOTS, router={"use": "scores", "min_scores": 5, "explore": 0})
    seed_scores(cv, "openai:gpt-6-luna", "quick", [5] * 6)
    route = cv.lab.propose_route("quick", "anthropic:claude-haiku-5-5", "", "mine")
    cv.lab.set_route_status(route, "accepted")
    assert cv.decide("auto", [{"role": "user", "content": QUICK}]).model == "anthropic:claude-haiku-5-5"


def test_score_proposals_and_automatic_changes(make):
    cv = make(slots=SLOTS, router={"use": "scores", "min_scores": 5, "auto_tune": False})
    seed_scores(cv, "openai:gpt-6-luna", "quick", [5] * 6)
    seed_scores(cv, "anthropic:claude-haiku-5-5", "quick", [3] * 6)
    assert "off" in tuning.auto(cv)
    proposals = tuning.propose_from_scores(cv)
    assert [(p["kind"], p["model"], p["previous"]) for p in proposals] == [("quick", "openai:gpt-6-luna", "anthropic:claude-haiku-5-5")]
    cv.config.auto_tune = True
    assert "accepted" in tuning.auto(cv) and cv.lab.pinned() == {"quick": "openai:gpt-6-luna"}
    # the new model does worse than the one it replaced: the next run rolls it back
    later = time.time() + 1
    for _ in range(6):
        turn = cv.store.add_turn("t", "api", "assistant", "x", model="openai:gpt-6-luna")
        cv.lab.add_score(turn, "openai:gpt-6-luna", "quick", "judge", 1, False, "", 0.0)
    cv.lab.db.execute("UPDATE scores SET ts = ? WHERE score = 5", (later - 10 * 86400,))
    result = tuning.auto(cv, now=later)
    assert "rolled back" in result and cv.lab.pinned() == {}
    assert "accepted" not in result  # the kind changed this week: nothing new is accepted


def test_the_weekly_report_counts_the_saving(make, fake):
    cv = make(slots=SLOTS)
    fake.on("openai:gpt-6-luna", "34236")
    cv.ask("openai:gpt-6-luna", [{"role": "user", "content": QUICK}])
    week = care.weekly(cv)
    assert week["answers"] == 1 and week["strongest"] == "anthropic:claude-opus-5-5"
    assert week["spend_if_strongest_usd"] == pytest.approx((100 * 4.0 + 50 * 20.0) / 1e6)
    assert week["saved_usd"] == pytest.approx(week["spend_if_strongest_usd"] - week["spend_usd"])
    assert "less than always using anthropic:claude-opus-5-5" in care.weekly_text(cv)


def test_report_week_json_and_tune_commands(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("CROSSVET_DB", str(tmp_path / "chat.db"))
    assert cli.main(["report", "--week", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["answers"] == 0
    assert cli.main(["tune", "scores"]) == 0 and "No proposal from scores" in capsys.readouterr().out
    assert cli.main(["tune", "auto"]) == 0 and "off" in capsys.readouterr().out
