"""auto: the kind of task -> a slot -> a model, explained; escalation; private requests; named models untouched."""

from __future__ import annotations

import pytest

from crossvet import routing
from crossvet.config import parse
from crossvet.providers import ProviderError, Reply

SLOTS = {"quick": ["openai:gpt-6-luna", "anthropic:claude-haiku-5-5"], "balanced": ["anthropic:claude-sonnet-5-5"],
         "strong": ["anthropic:claude-opus-5-5", "openai:gpt-6.1-sol"], "reviewer": ["openai:gpt-6.1-sol", "anthropic:claude-opus-5-5"]}
CODE = "Fix the race condition in this Go worker pool"
QUICK = "What is the ZIP code of 707 S Washington Blvd, Sarasota?"


@pytest.fixture(autouse=True)
def _keys(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "x")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "x")


@pytest.fixture
def auto(make):
    return make(slots=SLOTS)


def ask(text):
    return [{"role": "user", "content": text}]


def test_names_that_ask_crossvet_to_choose():
    assert routing.is_auto("auto") and routing.is_auto("crossvet/strong") and routing.is_auto("crossvet/cheapest")
    assert not routing.is_auto("default") and not routing.is_auto("sonnet") and not routing.is_auto("crossvet/turbo")
    assert "auto" in routing.menu_names() and "crossvet/private" not in routing.menu_names()


def test_code_goes_to_strong_and_quick_questions_to_quick(auto):
    code = auto.decide("auto", ask(CODE))
    assert (code.kind, code.slot, code.model) == ("code", "strong", "anthropic:claude-opus-5-5")
    assert code.ladder == ["anthropic:claude-opus-5-5", "openai:gpt-6.1-sol"]
    quick = auto.decide("auto", ask(QUICK))
    assert (quick.slot, quick.model) == ("quick", "openai:gpt-6-luna")
    assert quick.ladder == ["openai:gpt-6-luna", "anthropic:claude-haiku-5-5", "anthropic:claude-sonnet-5-5"]  # climbs, max_steps = 2
    assert "opus" in code.explain() and "race condition" in code.explain()


def test_hard_tasks_move_up_and_routes_can_be_changed(make):
    cv = make(slots=SLOTS, routes={"summarize": "balanced"})
    hard = cv.decide("auto", ask("Summarize the architecture trade-offs of this production migration"))
    assert hard.slot == "strong" and "hard tasks" in hard.reason
    assert cv.decide("auto", ask("Summarize this in two sentences: the lot sold six trucks.")).slot == "balanced"


def test_images_long_requests_slots_and_goals(make):
    cv = make(slots={**SLOTS, "vision": ["openai:gpt-6.1-sol"], "long": ["anthropic:claude-sonnet-5-5"]},
              router={"long_chars": 100})
    image = [{"role": "user", "content": [{"type": "text", "text": "What car is this?"},
                                          {"type": "image_url", "image_url": {"url": "data:image/png;base64,AA"}}]}]
    assert cv.decide("auto", image).slot == "vision"
    assert cv.decide("auto", ask("x " * 80)).slot == "long"
    assert cv.decide("crossvet/quick", ask(CODE)).slot == "quick"
    cheapest = cv.decide("crossvet/cheapest", ask(CODE))
    assert cheapest.model == "openai:gpt-6.1-sol" and cheapest.goal == "cheapest"
    assert cv.decide("crossvet/best", ask(CODE)).model == "anthropic:claude-opus-5-5"


def test_private_requests_never_reach_a_cloud_model(auto, make, fake):
    with pytest.raises(routing.PrivateRequest, match="no private model"):
        auto.decide("auto", ask("[private] my SSN is 123-45-6789, fill the credit form"))
    assert fake.calls == []
    local = make(slots={**SLOTS, "private": ["ollama:gemma3"]})
    assert local.decide("auto", ask("This is confidential: draft the offer letter")).model == "ollama:gemma3"
    off = make(slots=SLOTS, router={"private_auto": False})
    assert off.decide("auto", ask("This is confidential: draft the offer letter")).slot == "balanced"


def test_auto_answers_are_logged_with_their_decision(auto, fake):
    fake.on("anthropic:claude-opus-5-5", "Use a mutex around the map.")
    answer = auto.ask("auto", ask(CODE))
    assert answer.model == "anthropic:claude-opus-5-5" and answer.decision["slot"] == "strong"
    assert "auto: strong slot" in answer.footer()
    kept = auto.lab.decision(turn_id=answer.turn_id)
    assert kept["kind"] == "code" and kept["steps"] == [{"model": "anthropic:claude-opus-5-5", "outcome": "ok",
                                                          "turn": answer.turn_id}]


def test_escalation_after_an_error_or_an_empty_answer(auto, fake):
    fake.on("anthropic:claude-opus-5-5", ProviderError("HTTP 529 overloaded"))
    fake.on("openai:gpt-6.1-sol", "Guard the map with a mutex.")
    answer = auto.ask("auto", ask(CODE))
    assert answer.model == "openai:gpt-6.1-sol"
    assert [s["outcome"][:5] for s in answer.decision["steps"]] == ["error", "ok"]
    fake.script.clear()
    fake.on("openai:gpt-6-luna", Reply(text="", model="openai:gpt-6-luna"))
    fake.on("anthropic:claude-haiku-5-5", "34236")
    assert auto.ask("auto", ask(QUICK)).text == "34236"


def test_invalid_json_is_held_back_and_escalated(make, fake):
    cv = make(slots=SLOTS)
    fake.on("openai:gpt-6-luna", "Sure! year 2019, make Ford")
    fake.on("anthropic:claude-haiku-5-5", '{"year": 2019, "make": "Ford"}')
    pieces = list(cv.ask_stream("auto", ask('Extract as JSON: "Used 2019 Ford EcoSport"')))
    text = "".join(p for p in pieces if isinstance(p, str))
    assert text == '{"year": 2019, "make": "Ford"}'  # the bad answer was never shown


def test_escalation_stops_at_max_steps_and_can_be_off(make, fake):
    fake.on("anthropic:claude-opus-5-5", ProviderError("down"))
    fake.on("openai:gpt-6.1-sol", ProviderError("down too"))
    with pytest.raises(ProviderError, match="down too"):
        make(slots=SLOTS).ask("auto", ask(CODE))
    fake.calls.clear()
    with pytest.raises(ProviderError, match="down"):
        make(slots=SLOTS, router={"escalate": False}).ask("auto", ask(CODE))
    assert [c[0] for c in fake.calls] == ["anthropic:claude-opus-5-5"]


def test_a_named_model_is_never_switched(auto, fake):
    fake.on("anthropic:claude-opus-5-5", ProviderError("HTTP 500"))
    with pytest.raises(ProviderError):
        auto.ask("opus" if "opus" in auto.config.names else "anthropic:claude-opus-5-5", ask(CODE))
    assert [c[0] for c in fake.calls] == ["anthropic:claude-opus-5-5"]


def test_relay_with_auto_moves_on_after_an_error(auto, fake):
    fake.on("anthropic:claude-opus-5-5", ProviderError("HTTP 500"))
    fake.on("openai:gpt-6.1-sol", "done")
    body = {"messages": ask(CODE), "tools": [{"type": "function", "function": {"name": "run"}}]}
    _, answer = auto.relay("auto", body)
    assert answer.model == "openai:gpt-6.1-sol" and answer.decision["steps"][0]["outcome"].startswith("error")
    fake.script.clear()
    items = list(auto.relay_stream("auto", body))
    assert items[-1].decision["model"] == "anthropic:claude-opus-5-5"


def test_an_accepted_route_puts_its_model_first(auto):
    route = auto.lab.propose_route("code", "openai:gpt-6.1-sol", "anthropic:claude-opus-5-5", "test")
    auto.lab.set_route_status(route, "accepted")
    decision = auto.decide("auto", ask(CODE))
    assert decision.model == "openai:gpt-6.1-sol" and "accepted route" in decision.reason
    auto.lab.set_route_status(route, "rolled_back")
    assert auto.decide("auto", ask(CODE)).model == "anthropic:claude-opus-5-5"


def test_the_reviewer_slot_prefers_another_vendor(auto):
    decision = routing.decide(auto.config, ask("Review this plan and find the flaws"), author="openai:gpt-6.1-sol")
    assert decision.slot == "reviewer" and decision.model == "anthropic:claude-opus-5-5"


def test_built_in_slots_follow_the_keys(monkeypatch):
    from crossvet.config import builtin

    monkeypatch.delenv("OPENAI_API_KEY")
    cfg = builtin()
    assert all(m.startswith("anthropic:") for models in cfg.slots.values() for m in models)
    assert parse({}).slot_models("private") == []


@pytest.mark.parametrize(("text", "kind"), [
    ("Sarasota Ford is at 707 S Washington Blvd., Sarasota, FL 34236. What is its ZIP code? Number only.", "quick"),
    ("What is the ZIP code of 707 S Washington Blvd, Sarasota?", "quick"),
    ("Use the promo code SAVE10 at checkout. Is it still valid? Yes or no.", "quick"),
    ("Fix the race condition in this Go worker pool", "code"),
    ("Write a Python function roman_to_int(text)", "code"),
    ("Draft a two-sentence reply declining a Thursday test drive", "writing"),
])
def test_the_rules_name_the_kind(text, kind):
    from crossvet.classify import classify

    assert classify(text).kind == kind
