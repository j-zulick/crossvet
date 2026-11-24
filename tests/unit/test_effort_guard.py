"""Effort tiers and the model guard: decisions made in code, offline."""

import asyncio

import pytest
from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, LLMResult
from langchain_core.runnables import RunnableLambda

from open_deep_research import effort, guard
from open_deep_research.configuration import Configuration


def cfg(**values):
    return Configuration.from_runnable_config({"configurable": values})


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for name in ("EFFORT", "MAX_RESEARCHER_ITERATIONS", "REVIEW_PANEL_LIMIT", "ESCALATION_MODEL", "MAX_RUN_USD",
                 "REVIEW_DELIBERATION_ROUNDS", "MAX_REACT_TOOL_CALLS", "MAX_CONCURRENT_RESEARCH_UNITS", "REVIEW_BLIND_PASS_ENABLED"):
        monkeypatch.delenv(name, raising=False)


# --- tiers ---

def test_no_effort_changes_nothing():
    plain = Configuration()
    assert cfg() == plain
    assert cfg(effort="standard").max_researcher_iterations == plain.max_researcher_iterations


def test_quick_lowers_research_and_review():
    c = cfg(effort="quick")
    assert (c.max_concurrent_research_units, c.max_researcher_iterations, c.max_react_tool_calls) == (2, 2, 4)
    assert (c.review_panel_limit, c.review_deliberation_rounds, c.review_blind_pass_enabled) == (2, 0, False)


def test_deep_raises_research_and_review():
    c = cfg(effort="deep")
    assert c.max_researcher_iterations == 8 and c.max_react_tool_calls == 15
    assert c.review_deliberation_rounds == 2 and c.review_blind_pass_enabled is True


def test_your_own_setting_wins_over_the_tier(monkeypatch):
    assert cfg(effort="quick", max_researcher_iterations=5).max_researcher_iterations == 5
    monkeypatch.setenv("EFFORT", "quick")
    monkeypatch.setenv("REVIEW_PANEL_LIMIT", "3")
    c = cfg()
    assert c.review_panel_limit == 3 and c.max_react_tool_calls == 4


def test_unknown_or_auto_effort_is_standard():
    assert cfg(effort="auto").max_researcher_iterations == Configuration().max_researcher_iterations
    assert cfg(effort="turbo").max_researcher_iterations == Configuration().max_researcher_iterations


# --- classification ---

@pytest.mark.parametrize("question,tier", [
    ("When was the James Webb Space Telescope launched?", "quick"),
    ("How many moons does Jupiter have?", "quick"),
    ("Compare vented and solid brake rotors for towing.", "deep"),
    ("What changed in EU AI rules in 2026? Who enforces them? What are the fines? When do they apply?", "deep"),
    ("Tell me about the James Webb Space Telescope's mirror.", "standard"),
    ("", "standard"),
    ("x" * 450, "deep"),
])
def test_classify(question, tier):
    got, reason = effort.classify(question)
    assert got == tier and reason


def test_an_unclear_question_never_gets_less_than_standard():
    assert effort.classify("Brake rotors")[0] == "standard"
    assert effort.classify("What is the best strategy for replacing rotors?")[0] == "deep"  # short, but analytical wording


# --- panel limit ---

def test_limit_panel_takes_one_per_vendor_first():
    models = ["openai:a", "openai:b", "anthropic:c", "google_genai:d"]
    assert effort.limit_panel(models, 2) == ["openai:a", "anthropic:c"]
    assert effort.limit_panel(models, 3) == ["openai:a", "anthropic:c", "google_genai:d"]
    assert effort.limit_panel(models, 0) == models
    assert effort.limit_panel(["openai:a", "openai:b", "openai:c"], 2) == ["openai:a", "openai:b"]
    assert effort.limit_panel(["openrouter:x-ai/g", "openrouter:x-ai/h", "openrouter:z-ai/k"], 2) == ["openrouter:x-ai/g", "openrouter:z-ai/k"]


def test_describe_names_the_tier_and_values():
    line = effort.describe(cfg(effort="quick"))
    assert line.startswith("Effort: quick (2 parallel researchers, 2 research rounds, 4 tool calls each, panel of 2")


# --- escalation ---

def _fails(_):
    raise ValueError("structured output did not parse")


def test_escalation_only_after_the_first_model_fails():
    calls = []
    cheap = RunnableLambda(lambda v: calls.append("cheap") or "cheap answer")
    strong = RunnableLambda(lambda v: calls.append("strong") or "strong answer")
    config = {"configurable": {"thread_id": "t-ok"}}
    assert asyncio.run(guard.with_escalation(cheap, strong, "compression", "p:cheap", "p:strong").ainvoke("x", config)) == "cheap answer"
    assert calls == ["cheap"] and guard.escalations(config) == []


def test_escalation_is_recorded_for_the_run():
    strong = RunnableLambda(lambda v: "strong answer")
    config = {"configurable": {"thread_id": "t-esc"}}
    model = guard.with_escalation(RunnableLambda(_fails), strong, "summarization", "p:cheap", "p:strong")
    assert asyncio.run(model.ainvoke("x", config)) == "strong answer"
    assert model.invoke("x", config) == "strong answer"
    assert guard.escalations(config) == ["summarization: p:cheap → p:strong (ValueError)"] * 2
    assert guard.escalations({"configurable": {"thread_id": "another-run"}}) == []


def test_escalation_target():
    assert guard.escalation_target("p:a", "") == ""
    assert guard.escalation_target("p:a", "p:a") == ""
    assert guard.escalation_target("p:a", " p:b ") == "p:b"


def test_stage_model_escalates_with_the_stronger_models_own_shape(monkeypatch):
    from open_deep_research import deep_researcher as dr

    built = {}

    def fake_build(name, max_tokens, config, tags=None):
        built[name] = True
        return RunnableLambda(_fails) if name == "local:cheap" else RunnableLambda(lambda v: f"answer from {name}")

    monkeypatch.setattr(dr, "build_chat_model", fake_build)
    shaped = []
    model = dr.stage_model({"model": "local:cheap"}, lambda m, name: shaped.append(name) or m,
                           role="compression", escalation={"model": "local:strong"})
    config = {"configurable": {"thread_id": "t-stage"}}
    assert asyncio.run(model.ainvoke("x", config)) == "answer from local:strong"
    assert shaped == ["local:cheap", "local:strong"]
    assert guard.escalations(config) == ["compression: local:cheap → local:strong (ValueError)"]
    plain = dr.stage_model({"model": "local:strong"}, role="compression", escalation={"model": "local:strong"})
    assert asyncio.run(plain.ainvoke("x")) == "answer from local:strong"  # same model: nothing to escalate to


def test_escalation_for_reads_the_setting(monkeypatch):
    from open_deep_research import deep_researcher as dr

    monkeypatch.setattr(dr, "get_api_key_for_model", lambda model, config: f"key-for-{model}")
    base = {"model": "openai:small", "max_tokens": 100, "api_key": "k", "tags": ["t"]}
    assert dr.escalation_for(base, cfg(), {}) is None
    stronger = dr.escalation_for(base, cfg(escalation_model="anthropic:big"), {})
    assert stronger == {"model": "anthropic:big", "max_tokens": 100, "api_key": "key-for-anthropic:big", "tags": ["t"]}


# --- spend cap ---

def _result(cost=None, tokens=(0, 0)):
    message = AIMessage(content="ok", response_metadata={"cost": cost} if cost is not None else {},
                        usage_metadata={"input_tokens": tokens[0], "output_tokens": tokens[1], "total_tokens": sum(tokens)})
    return LLMResult(generations=[[ChatGeneration(message=message)]])


def test_budget_guard_stops_the_call_after_the_cap():
    async def run():
        g = guard.BudgetGuard(0.10)
        await g.on_chat_model_start({}, [], run_id="r1", invocation_params={"model": "m"})
        await g.on_llm_end(_result(cost=0.06), run_id="r1")
        await g.on_chat_model_start({}, [], run_id="r2", invocation_params={"model": "m"})  # 0.06 < cap: allowed
        await g.on_llm_end(_result(cost=0.06), run_id="r2")
        with pytest.raises(guard.BudgetExceeded):
            await g.on_chat_model_start({}, [], run_id="r3", invocation_params={"model": "m"})
        return g

    g = asyncio.run(run())
    assert g.tripped and round(g.spent, 2) == 0.12 and "of a $0.10 cap" in g.summary()
    assert guard.BudgetGuard.raise_error is True


def test_budget_guard_prices_tokens_and_counts_unknown(monkeypatch):
    from open_deep_research import bench

    monkeypatch.setattr(bench, "price_for", lambda model, prices: (1e-6, 2e-6) if model == "openai:known" else None)

    async def run():
        g = guard.BudgetGuard(5)
        await g.on_chat_model_start({}, [], run_id="a", invocation_params={"model": "known"}, metadata={"ls_provider": "openai"})
        await g.on_llm_end(_result(tokens=(1000, 500)), run_id="a")
        await g.on_chat_model_start({}, [], run_id="b", invocation_params={"model": "mystery"})
        await g.on_llm_end(_result(tokens=(1000, 500)), run_id="b")
        return g

    g = asyncio.run(run())
    assert g.spent == pytest.approx(0.002) and g.unpriced_calls == 1
    assert "1 call(s) had no known price" in g.summary()


def test_no_cap_means_no_callback():
    assert guard.budget_callbacks(0) == [] and len(guard.budget_callbacks(1.5)) == 1


# --- command line ---

def test_effort_auto_is_resolved_in_code(monkeypatch, capsys):
    from open_deep_research import cli

    monkeypatch.setenv("EFFORT", "")
    monkeypatch.setenv("MAX_RUN_USD", "0")
    assert cli.set_run_limits("auto", None, "When was the telescope launched?") == []
    import os

    assert os.environ["EFFORT"] == "quick"
    assert "effort: quick (chosen because" in capsys.readouterr().err
    budget = cli.set_run_limits("deep", 2.5, "anything")
    assert os.environ["EFFORT"] == "deep" and budget[0].max_usd == 2.5


def test_research_and_try_accept_the_flags():
    from open_deep_research import cli

    args = cli.build_parser().parse_args(["research", "Q?", "--effort", "quick", "--max-usd", "1"])
    assert args.effort == "quick" and args.max_usd == 1.0


def test_budget_guard_stops_a_real_model_call():
    from langchain_core.language_models.fake_chat_models import FakeListChatModel

    async def run():
        g = guard.BudgetGuard(0.01)
        g.spent = 0.02
        model = FakeListChatModel(responses=["never sent"])
        with pytest.raises(guard.BudgetExceeded):
            await model.ainvoke("hello", config={"callbacks": [g]})
        return g

    assert asyncio.run(run()).tripped


def test_api_resolves_effort_auto_from_the_question(monkeypatch):
    from open_deep_research import api

    seen = {}

    class Graph:
        async def ainvoke(self, state, config):
            seen.update(config["configurable"])
            return {}

    monkeypatch.setattr(api, "_graph", lambda edition: Graph())
    api.run("How many moons does Jupiter have?", {"effort": "auto"})
    assert seen["effort"] == "quick"
    api.run("Compare vented and solid rotors for towing.", {"effort": "Auto"})
    assert seen["effort"] == "deep"
    api.run("How many moons does Jupiter have?", {"effort": "deep"})
    assert seen["effort"] == "deep"  # a tier you name is kept
