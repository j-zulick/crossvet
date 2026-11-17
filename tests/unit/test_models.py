"""v1.6: any model in any role (model factory, capabilities, cost, role split)."""

import asyncio
import json
import time

import pytest
from langchain_core.messages import AIMessage, HumanMessage

from open_deep_research import cross_vendor_review, deep_agent, deep_researcher, models, utils
from open_deep_research.configuration import Configuration


@pytest.fixture(autouse=True)
def clean_env(monkeypatch, tmp_path):
    for k in ("OPENROUTER_PROVIDER_ORDER", "OPENROUTER_ALLOW_FALLBACKS", "OPENROUTER_DATA_COLLECTION",
              "GET_API_KEYS_FROM_CONFIG", "SUPERVISOR_MODEL", "RESEARCHER_MODEL", "RESEARCH_MODEL"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    monkeypatch.setattr(models, "CAPABILITY_CACHE", tmp_path / "openrouter-models.json")


def test_provider_maker_and_id():
    assert models.provider_of("openrouter:x-ai/grok-4") == "openrouter"
    assert models.model_id("openrouter:x-ai/grok-4") == "x-ai/grok-4"
    assert models.maker_of("openrouter:z-ai/glm-5") == "z-ai"
    assert models.maker_of("anthropic:claude-sonnet-5-5") == "anthropic"
    assert models.is_routed("openrouter:a/b") and models.is_routed("local:gemma") and not models.is_routed("openai:gpt-6")


def test_factory_builds_each_provider(monkeypatch):
    from langchain_openai import ChatOpenAI
    from langchain_openrouter import ChatOpenRouter

    monkeypatch.setenv("OPENROUTER_DATA_COLLECTION", "deny")
    orm = models.build_chat_model("openrouter:z-ai/glm-5", 300, tags=["t"])
    assert isinstance(orm, ChatOpenRouter)
    assert orm.model_name == "z-ai/glm-5" and orm.max_tokens == 300
    assert orm.openrouter_provider == {"data_collection": "deny"}
    assert orm.app_title == "Crossvet" and orm.openrouter_api_key.get_secret_value() == "test-key"
    local = models.build_chat_model("local:gemma-3-12b", 200)
    assert isinstance(local, ChatOpenAI) and local.model_name == "gemma-3-12b"


def test_openrouter_key_from_run_config(monkeypatch):
    monkeypatch.setenv("GET_API_KEYS_FROM_CONFIG", "true")
    cfg = {"configurable": {"apiKeys": {"OPENROUTER_API_KEY": "from-config"}}}
    assert models.api_key_for("openrouter:a/b", cfg) == "from-config"
    assert utils.get_api_key_for_model("openrouter:a/b", cfg) == "from-config"
    assert utils.get_api_key_for_model("anthropic:claude", cfg) is None


def test_every_langgraph_stage_accepts_openrouter_and_local():
    from langchain_openai import ChatOpenAI
    from langchain_openrouter import ChatOpenRouter

    built = deep_researcher.stage_model({"model": "openrouter:x-ai/grok-4", "max_tokens": 100, "tags": ["x"]})
    assert isinstance(built, ChatOpenRouter)
    shaped = deep_researcher.stage_model({"model": "local:gemma", "max_tokens": 100}, lambda m: m.bind_tools([]))
    assert isinstance(shaped.bound, ChatOpenAI)
    summarizer = utils.stage_chat_model("openrouter:qwen/qwen3-max", 100, {"configurable": {}})
    assert isinstance(summarizer, ChatOpenRouter)


def test_structured_output_method_follows_capabilities():
    assert models.structured_output_kwargs("anthropic:claude-sonnet-5-5") == {"method": "json_schema"}
    assert models.structured_output_kwargs("openrouter:anthropic/claude-sonnet-5.5") == {"method": "json_schema"}
    assert models.structured_output_kwargs("openai:gpt-6") == {}
    # Unknown OpenRouter model: a forced tool call works on any model with tools.
    assert models.structured_output_kwargs("openrouter:nobody/unknown-1") == {"method": "function_calling"}
    models.save_openrouter_catalog([{"id": "nobody/unknown-1", "supported_parameters": ["tools", "structured_outputs"]}])
    assert models.structured_output_kwargs("openrouter:nobody/unknown-1") == {"method": "json_schema"}


def test_catalog_capabilities_and_unmet_needs():
    models.save_openrouter_catalog([
        {"id": "a/tools", "supported_parameters": ["tools", "max_tokens"], "pricing": {"prompt": "0.000001", "completion": "0.000002"}},
        {"id": "a/plain", "supported_parameters": ["max_tokens"]},
    ])
    caps = models.capabilities("openrouter:a/tools")
    assert caps["source"] == "openrouter-catalog" and caps["tool_calling"] is True and caps["prompt_price"] == 1e-6
    assert models.unmet_needs("openrouter:a/plain", "supervisor") == ["tool calls"]
    assert models.unmet_needs("openrouter:a/plain", "reviewer") == ["structured output"]
    assert models.unmet_needs("openrouter:a/tools", "researcher") == []
    assert models.unmet_needs("openai:gpt-6", "supervisor") == []  # unknown counts as met


def test_stale_catalog_is_ignored():
    models.CAPABILITY_CACHE.write_text(json.dumps({"fetched_at": time.time() - 30 * 24 * 3600,
                                                   "models": {"a/plain": {"tool_calling": False}}}))
    assert models.capabilities("openrouter:a/plain")["source"] != "openrouter-catalog"


def test_cost_from_response_metadata():
    assert models.cost_of(AIMessage(content="x", response_metadata={"cost": 0.0012})) == 0.0012
    assert models.cost_of(AIMessage(content="x", response_metadata={"token_usage": {"cost": 0.5}})) == 0.5
    assert models.cost_of(AIMessage(content="x")) is None


def test_role_split_falls_back_to_research_model(monkeypatch):
    monkeypatch.setenv("RESEARCH_MODEL", "openai:gpt-6")
    cfg = Configuration.from_runnable_config({"configurable": {}})
    assert cfg.model_for("supervisor") == cfg.model_for("researcher") == "openai:gpt-6"
    monkeypatch.setenv("SUPERVISOR_MODEL", "anthropic:claude-opus-5-5")
    monkeypatch.setenv("RESEARCHER_MODEL", "openrouter:qwen/qwen3-max")
    cfg = Configuration.from_runnable_config({"configurable": {}})
    assert cfg.model_for("supervisor") == "anthropic:claude-opus-5-5"
    assert cfg.model_for("researcher") == "openrouter:qwen/qwen3-max"
    assert cfg.model_for("compression") == cfg.compression_model


def test_doctor_flags_a_model_without_tool_calls(monkeypatch):
    from open_deep_research import doctor

    models.save_openrouter_catalog([{"id": "a/plain", "supported_parameters": ["max_tokens"]}])
    monkeypatch.setenv("SUPERVISOR_MODEL", "openrouter:a/plain")
    findings = doctor.check()
    assert any(f.level == "FAIL" and "does not support tool calls" in f.message and "supervisor" in f.message for f in findings)


def test_graph_routes_supervisor_and_researcher_to_their_models(monkeypatch):
    """Full LangGraph run with every stage on OpenRouter ids: each stage builds its own model."""
    from tests.unit.test_end_to_end import REPORT, SOURCE_URL, ScriptedModel

    seen: list[str] = []
    model = ScriptedModel(calls=[])

    def fake_build(name, max_tokens=None, config=None, tags=None):
        seen.append(name)
        return model

    async def fake_search(queries, **kwargs):
        return [{"query": q, "results": [{"url": SOURCE_URL, "title": "t", "content": "Solar additions grew strongly in 2025.",
                                           "raw_content": "Solar additions grew strongly in 2025. " * 20}]} for q in queries]

    monkeypatch.setattr(deep_researcher, "build_chat_model", fake_build)
    monkeypatch.setattr(models, "build_chat_model", fake_build)
    monkeypatch.setattr(utils, "tavily_search_async", fake_search)
    monkeypatch.setattr(cross_vendor_review, "build_reviewer", lambda *a, **k: model)
    for key in ("REQUIRE_APPROVAL", "RUN_EXPORT_PATH", "REVIEW_DELIBERATION_ROUNDS"):
        monkeypatch.delenv(key, raising=False)
    env = {"SEARCH_API": "tavily", "MAX_RESEARCHER_ITERATIONS": "2", "MAX_REACT_TOOL_CALLS": "2",
           "CROSS_VENDOR_REVIEW_ENABLED": "false", "RESEARCH_MODEL": "openrouter:r/brief",
           "SUPERVISOR_MODEL": "openrouter:s/orchestrator", "RESEARCHER_MODEL": "openrouter:w/researcher",
           "SUMMARIZATION_MODEL": "openrouter:m/summarizer", "COMPRESSION_MODEL": "openrouter:c/compressor",
           "FINAL_REPORT_MODEL": "openrouter:f/writer"}
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    out = asyncio.run(deep_researcher.deep_researcher.ainvoke({"messages": [HumanMessage(content="Solar in 2025?")]}, {"configurable": {}}))
    assert out["final_report"].startswith(REPORT.split("\n")[0])
    for name in env.values():
        if name.startswith("openrouter:") and name != "openrouter:m/summarizer":
            assert name in seen, name
    assert "openrouter:m/summarizer" in seen  # webpage summaries go through the factory too
    assert "supervisor" in model.calls and "researcher" in model.calls


def test_deep_agent_researcher_subagent_gets_its_own_model():
    captured = {}

    import deepagents

    def fake_create(**kwargs):
        captured.update(kwargs)
        return object()

    original = deepagents.create_deep_agent
    deepagents.create_deep_agent = fake_create
    try:
        deep_agent.build_agent("orchestrator-model", [], "researcher-model")
        assert captured["model"] == "orchestrator-model"
        assert captured["subagents"][0]["model"] == "researcher-model"
        deep_agent.build_agent("orchestrator-model", [])
        assert "model" not in captured["subagents"][0]
    finally:
        deepagents.create_deep_agent = original
