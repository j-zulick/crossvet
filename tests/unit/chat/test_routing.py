"""The classifier and the router: decisions made in code, each with a reason."""

import pytest

from crossvet.chat.classify import classify
from crossvet.chat.config import Config, load, parse
from crossvet.chat.routing import route

from .conftest import CONFIG


@pytest.mark.parametrize("text,kind", [
    ("What is the capital of Australia?", "quick"),
    ("Summarize this article in three bullets: ...", "summarize"),
    ("Extract all the email addresses from the text below as JSON", "extract"),
    ("Translate this paragraph into Spanish", "translate"),
    ("Draft an email to my landlord about the broken heater", "writing"),
    ("Fix the bug in this Python function:\n```python\ndef f(x): return x +\n```", "code"),
    ("Why does my SQL query time out on large tables?", "code"),
    ("Compare leasing and buying a car over five years", "reasoning"),
    ("What is trending on X right now about the outage?", "fresh"),
    ("Review this plan and find where it fails", "review"),
    ("Tell me about lighthouses", "general"),
    ("", "general"),
])
def test_kinds(text, kind):
    task = classify(text)
    assert task.kind == kind and task.reason


def test_difficulty_rises_for_hard_words_long_text_and_many_parts():
    assert classify("Write a function to add two numbers in Python").difficulty == 2
    assert classify("Design the architecture for a multi-tenant billing service in Python").difficulty == 3
    assert classify("Summarize: " + "word " * 400).difficulty == 2
    assert classify("Draft an email. What tone? What length? Who signs it?").difficulty == 3


def test_unclear_requests_are_never_quick():
    assert classify("Brake rotors").kind == "general"
    assert classify("What is the best strategy for entering the German market over three years?").kind == "reasoning"


def test_json_is_noticed():
    assert classify("List the planets as JSON").wants_json and not classify("List the planets").wants_json


def test_route_follows_the_table_and_explains():
    cfg = parse(CONFIG)
    d = route("What is the capital of Australia?", cfg)
    assert (d.slot, d.candidates) == ("quick", ["openai:small", "anthropic:small"])
    assert "quick task" in d.explain() and "openai:small" in d.explain()
    assert route("Fix this Python bug", cfg).slot == "strong"
    assert route("What's the latest news on the merger today?", cfg).candidates == ["xai:grok"]
    assert route("Review this plan and poke holes in it", cfg).slot == "reviewer"


def test_hard_tasks_and_effort_move_along_the_ladder():
    cfg = parse(CONFIG)
    assert route("Draft an email to my landlord", cfg).slot == "balanced"
    assert route("Draft a comprehensive in-depth proposal for the board", cfg).slot == "strong"
    assert route("Draft an email to my landlord", cfg, effort="high").slot == "strong"
    assert route("Draft an email to my landlord", cfg, effort="low").slot == "quick"
    assert route("What is the capital of Australia?", cfg, effort="low").slot == "quick"


def test_forced_slot_and_bad_slot():
    cfg = parse(CONFIG)
    assert route("anything", cfg, slot="strong").candidates[0] == "anthropic:big"
    with pytest.raises(ValueError):
        route("anything", cfg, slot="turbo")


def test_long_input_goes_to_the_long_slot():
    cfg = parse(CONFIG)
    d = route("Summarize this: " + "x" * 60_000, cfg)
    assert d.slot == "long" and d.candidates == ["google:wide"]
    assert any("too long" in r for r in d.reasons)


def test_too_small_models_are_skipped_within_a_slot():
    data = {**CONFIG, "models": {**CONFIG["models"], "openai:small": {"context": 500}}}
    d = route("Summarize this: " + "x" * 6000, parse(data))
    assert d.candidates == ["anthropic:small"]


def test_empty_slot_falls_back_to_the_nearest():
    cfg = parse({"slots": {"strong": ["openai:big"]}})
    d = route("What is the capital of Australia?", cfg)
    assert d.candidates == ["openai:big"] and any("empty" in r for r in d.reasons)
    assert route("What's the news today?", cfg).candidates == ["openai:big"]
    assert route("hi", Config()).candidates == []


def test_config_rejects_unknown_slots_and_routes(tmp_path, monkeypatch):
    with pytest.raises(ValueError):
        parse({"slots": {"turbo": ["openai:x"]}})
    with pytest.raises(ValueError):
        parse({"routes": {"code": "turbo"}})
    file = tmp_path / "crossvet-chat.toml"
    file.write_text('[slots]\nquick = ["openai:a"]\n[routes]\ncode = "quick"\n[limits]\nmax_usd_per_day = 2.5\n')
    monkeypatch.setenv("CROSSVET_CHAT_CONFIG", str(file))
    cfg = load()
    assert cfg.slots["quick"] == ["openai:a"] and cfg.routes["code"] == "quick" and cfg.max_usd_per_day == 2.5
    assert cfg.routes["writing"] == "balanced"  # defaults kept
