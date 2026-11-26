"""The one path every request takes: the named model answers, guards run first, the turn is logged."""

from __future__ import annotations

import pytest

from crossvet.core import Answer, BudgetExceeded
from crossvet.providers import AccountError, ProviderError, Reply

ASK = [{"role": "user", "content": "Is a 2019 Honda CR-V with 48,000 miles low or high mileage? One sentence."}]


def test_the_named_model_answers_and_nothing_else_is_called(cv, fake):
    fake.on("openai:gpt-6-luna", "Low for its age.")
    answer = cv.ask("luna", ASK, app="test")
    assert answer.text == "Low for its age." and answer.model == "openai:gpt-6-luna"
    assert [m for m, _ in fake.calls] == ["openai:gpt-6-luna"]


def test_no_model_named_goes_to_the_default(cv, fake):
    assert cv.ask(None, ASK).model == "anthropic:claude-sonnet-5-5"


def test_the_turn_is_logged_with_tokens_and_list_price_cost(cv, fake):
    fake.on("anthropic:claude-opus-5-5", Reply("Done.", "", input_tokens=1000, output_tokens=500))
    answer = cv.ask("claude", ASK, thread="t1", app="test")
    assert answer.cost == pytest.approx((1000 * 4 + 500 * 20) / 1e6)
    turns = cv.store.turns("t1")
    assert [(t.role, t.model) for t in turns] == [("user", ""), ("assistant", "anthropic:claude-opus-5-5")]
    assert turns[0].content == ASK[0]["content"] and turns[1].cost == answer.cost
    assert turns[1].meta["input_tokens"] == 1000 and answer.turn_id == turns[1].id


def test_a_provider_reported_cost_wins(cv, fake):
    fake.on("openai:gpt-6.1-sol", Reply("x", "", input_tokens=10, output_tokens=10, cost=0.5))
    assert cv.ask("gpt", ASK).cost == 0.5


def test_a_model_without_a_price_logs_no_cost(cv, fake):
    answer = cv.ask("google:gemini-x", ASK)
    assert answer.cost is None and "price unknown" in answer.footer()


def test_streaming_yields_pieces_then_the_answer(cv, fake):
    fake.on("openai:gpt-6-luna", "Low for its age.")
    items = list(cv.ask_stream("luna", ASK))
    assert "".join(i for i in items if isinstance(i, str)) == "Low for its age."
    assert isinstance(items[-1], Answer)


def test_a_failure_names_the_model_and_nothing_switches(cv, fake):
    fake.on("openai:gpt-6.1-sol", ProviderError("HTTP 500 from api.openai.com"))
    with pytest.raises(ProviderError):
        cv.ask("gpt", ASK)
    assert [m for m, _ in fake.calls] == ["openai:gpt-6.1-sol"]
    assert cv.store.recent() == []


def test_a_refused_account_is_not_called_again(cv, fake):
    fake.on("openai:gpt-6.1-sol", AccountError("HTTP 401 from api.openai.com"))
    with pytest.raises(AccountError):
        cv.ask("gpt", ASK)
    with pytest.raises(AccountError, match="refused your key.*not called again"):
        cv.ask("luna", ASK)  # same provider
    assert len(fake.calls) == 1
    assert cv.ask("claude", ASK).model == "anthropic:claude-opus-5-5"  # other providers still work


def test_the_daily_cap_stops_a_call_before_it_is_made(make, fake):
    cv = make(limits={"max_usd_per_day": 0.01})
    fake.on("anthropic:claude-opus-5-5", Reply("x", "", input_tokens=1000, output_tokens=1000))
    cv.ask("claude", ASK)  # 0.024
    with pytest.raises(BudgetExceeded, match="daily cap"):
        cv.ask("claude", ASK)
    assert len(fake.calls) == 1


def test_the_per_call_cap_uses_the_worst_case(make, fake):
    cv = make(limits={"max_usd_per_call": 0.01, "max_output_tokens": 1000})
    with pytest.raises(BudgetExceeded, match="per-call cap"):
        cv.ask("claude", ASK)  # 1000 output tokens at $20/M = $0.02
    assert cv.ask("luna", ASK).model == "openai:gpt-6-luna"
    assert [m for m, _ in fake.calls] == ["openai:gpt-6-luna"]


def test_an_agents_request_is_passed_through_with_an_output_limit(cv, fake):
    call = {"id": "c1", "type": "function", "function": {"name": "lookup_vin", "arguments": "{}"}}
    fake.on("anthropic:claude-opus-5-5", Reply("", "", tool_calls=[call]))
    body = {"messages": ASK, "tools": [{"type": "function", "function": {"name": "lookup_vin"}}], "temperature": 0}
    raw, answer = cv.relay("claude", body, thread="t2", app="hermes")
    sent = fake.relayed[0][1]
    assert sent["max_tokens"] == 1000 and sent["tools"] == body["tools"] and sent["temperature"] == 0
    assert answer.tool_calls == [call]
    assert cv.store.turns("t2")[-1].content == "(tool calls: lookup_vin)"


def test_relay_keeps_the_clients_own_output_limit(cv, fake):
    cv.relay("gpt", {"messages": ASK, "tools": [], "max_completion_tokens": 50})
    assert "max_tokens" not in fake.relayed[0][1]


def test_models_and_cost_text(cv, fake):
    text = cv.models_text()
    assert "anthropic:claude-sonnet-5-5 (sonnet)" in text and "[default]" in text and "[no key]" in text
    assert "nothing yet" in cv.cost_text()
    cv.ask("luna", ASK, thread="a")
    cv.ask("google:g", ASK, thread="a")
    text = cv.cost_text(thread="a")
    assert "openai:gpt-6-luna" in text and "1 without a price" in text and "total" in text
