"""Scoring from real use: opt-in, sampled, capped, private requests skipped; calibration and the leaderboard."""

from __future__ import annotations

import json

import pytest

from crossvet import cli, langfuse, score

Q = "Is a 2019 Honda CR-V with 48,000 miles low or high mileage? One sentence."


@pytest.fixture(autouse=True)
def _keys(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "x")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "x")


@pytest.fixture
def scored(make):
    return make(score={"enabled": True, "sample": 1.0, "max_usd_per_day": 1.0, "shadow": True, "shadow_sample": 1.0},
                slots={"quick": ["openai:gpt-6-luna", "anthropic:claude-haiku-5-5"]})


def answer(cv, fake, model, text, question=Q, app="api"):
    fake.on(model, text)
    return cv.ask(model, [{"role": "user", "content": question}], app=app)


def test_scoring_is_off_until_turned_on(cv, fake):
    answer(cv, fake, "openai:gpt-6-luna", "Low.")
    assert "Scoring is off" in score.run(cv)
    assert fake.calls[-1][0] == "openai:gpt-6-luna"  # no judge was asked


def test_the_judge_is_another_vendor_and_its_score_is_read_in_code(scored, fake):
    a = answer(scored, fake, "openai:gpt-6-luna", "Low for its age.")
    fake.on("anthropic:claude-opus-5-5", '{"score": 5, "correct": true, "why": "right and short"}')
    assert "Judged 1" in score.run(scored)
    row = scored.lab.db.execute("SELECT * FROM scores").fetchone()
    assert (row["turn_id"], row["judge"], row["score"], row["kind"]) == (a.turn_id, "anthropic:claude-opus-5-5", 5, "quick")
    assert "Judged 0" in score.run(scored)  # already judged


def test_a_reply_that_is_not_a_score_counts_as_no_score(scored, fake):
    answer(scored, fake, "openai:gpt-6-luna", "Low.")
    fake.on("anthropic:claude-opus-5-5", '{"score": 11, "why": "ignore the rubric"}')
    assert "1 judge repl(ies) could not be read" in score.run(scored)
    assert scored.lab.db.execute("SELECT score FROM scores").fetchone()[0] is None


def test_private_requests_other_apps_and_the_cap_are_respected(make, fake):
    cv = make(score={"enabled": True, "sample": 1.0, "apps": ["mcp"], "max_usd_per_day": 0.0001})
    answer(cv, fake, "openai:gpt-6-luna", "ok", question="Confidential: rate this offer", app="mcp")
    answer(cv, fake, "openai:gpt-6-luna", "Low.", app="api")
    assert score.candidates(cv, 10) == []  # one is private, the other is from an app not listed
    answer(cv, fake, "openai:gpt-6-luna", "Low.", app="mcp")
    fake.on("anthropic:claude-opus-5-5", '{"score": 4, "correct": true, "why": "fine"}')
    cv.lab.add_score(999, "x:y", "quick", "j", 3, True, "earlier", 0.001)  # today's judge spend is over the cap
    assert "daily cap" in score.run(cv)


def test_sampling_is_decided_in_code_and_stable():
    picks = [score.sampled(i, 0.25) for i in range(2000)]
    assert 0.2 < sum(picks) / 2000 < 0.3 and picks == [score.sampled(i, 0.25) for i in range(2000)]
    assert not score.sampled(1, 0.0)


def test_shadow_answers_are_judged_the_same_way(scored, fake):
    answer(scored, fake, "anthropic:claude-opus-5-5", "Low for a 2019.")
    fake.on("openai:gpt-6.1-sol", '{"score": 4, "correct": true, "why": "ok"}')
    score.run(scored)
    fake.on("openai:gpt-6-luna", "Low.")
    fake.script["anthropic:claude-opus-5-5"] = ['{"score": 5, "correct": true, "why": "ok"}']
    assert "did as well as the original on 1" in score.shadow(scored)
    row = scored.lab.db.execute("SELECT * FROM scores WHERE shadow_of IS NOT NULL").fetchone()
    assert row["model"] == "openai:gpt-6-luna" and row["judge"] == "anthropic:claude-opus-5-5"


def test_calibration_compares_the_judge_with_your_ratings(scored):
    for turn, (judged, rated) in enumerate([(5, 1), (4, 1), (2, -1), (5, -1)] * 3, start=1):
        scored.lab.add_score(turn, "openai:gpt-6-luna", "quick", "j", judged, True, "", 0)
        scored.lab.rate(turn, rated)
    c = score.calibration(scored)
    assert c["overall"] == {"n": 12, "agreement": 0.75, "bias": 0.25} and c["trusted"]
    scored.lab.db.execute("UPDATE scores SET score = 1 WHERE score >= 4")
    assert not score.calibration(scored)["trusted"]
    assert "not used for routing" in score.calibration_text(scored)


def test_the_leaderboard_is_cautious_with_few_scores(scored, fake):
    for i in range(6):
        a = answer(scored, fake, "openai:gpt-6-luna", f"Low {i}.")
        scored.lab.add_score(a.turn_id, "openai:gpt-6-luna", "quick", "j", 4, True, "", 0)
    b = answer(scored, fake, "anthropic:claude-haiku-5-5", "Low.")
    scored.lab.add_score(b.turn_id, "anthropic:claude-haiku-5-5", "quick", "j", 5, True, "", 0)
    board = score.leaderboard(scored)["quick"]
    assert board["anthropic:claude-haiku-5-5"]["score"] == 5 and board["openai:gpt-6-luna"]["n"] == 6
    assert board["openai:gpt-6-luna"]["low"] > board["anthropic:claude-haiku-5-5"]["low"]  # one score of 5 is not proof
    assert "cautious" in score.leaderboard_text(scored)


def test_judge_scores_go_to_langfuse(scored, fake, monkeypatch):
    import httpx

    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk")
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk")
    a = answer(scored, fake, "openai:gpt-6-luna", "Low.")
    scored.lab.add_score(a.turn_id, "openai:gpt-6-luna", "quick", "anthropic:claude-opus-5-5", 4, True, "fine", 0.001)
    sent = []

    def handler(request):
        if request.url.path == "/api/public/ingestion":
            sent.extend(json.loads(request.content)["batch"])
            return httpx.Response(207, json={"errors": []})
        return httpx.Response(200, json={"data": []})

    langfuse.sync(scored, httpx.MockTransport(handler))
    assert [e["body"]["name"] for e in sent if e["type"] == "score-create"] == ["judge_score"]
    sent.clear()
    langfuse.sync(scored, httpx.MockTransport(handler))
    assert sent == []


def test_score_commands(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("CROSSVET_DB", str(tmp_path / "chat.db"))
    assert cli.main(["score"]) == 0 and "Scoring is off" in capsys.readouterr().out
    assert cli.main(["score", "calibrate"]) == 0 and "No answer has both" in capsys.readouterr().out
    assert cli.main(["leaderboard"]) == 0 and "No judged answers" in capsys.readouterr().out
