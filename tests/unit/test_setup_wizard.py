"""Tests for crossvet-setup (offline: provider APIs are mocked)."""

import asyncio
import json
import os
import stat

import httpx

from open_deep_research import setup_wizard as sw
from open_deep_research.setup_wizard import Discovery

OPENAI_IDS = ["gpt-4.1", "gpt-4.1-mini", "gpt-5.5", "gpt-5.6-sol", "gpt-5.6-terra", "gpt-5.6-mini", "gpt-realtime-2.1",
              "gpt-image-2", "text-embedding-3-large", "gpt-5.5-2026-06-01", "o4-mini"]
ANTHROPIC_IDS = ["claude-sonnet-5-5", "claude-haiku-5-5", "claude-opus-5-5", "claude-sonnet-4-5-20250929"]
GOOGLE_IDS = ["gemini-3.8-flash", "gemini-3.1-pro-preview", "gemini-3.5-flash-lite", "gemini-2.5-flash"]


def handler(request: httpx.Request) -> httpx.Response:
    url = str(request.url)
    if "api.openai.com" in url:
        if request.headers.get("authorization") != "Bearer ok-openai":
            return httpx.Response(401, json={})
        return httpx.Response(200, json={"data": [{"id": i} for i in OPENAI_IDS]})
    if "api.anthropic.com" in url:
        assert request.headers["anthropic-version"] == "2023-06-01"
        return httpx.Response(200, json={"data": [{"id": i} for i in ANTHROPIC_IDS]})
    if "generativelanguage" in url:
        models = [{"name": f"models/{i}", "supportedGenerationMethods": ["generateContent"]} for i in GOOGLE_IDS]
        models.append({"name": "models/text-embedding-005", "supportedGenerationMethods": ["embedContent"]})
        return httpx.Response(200, json={"models": models})
    if "openrouter.ai" in url:
        return httpx.Response(200, json={"data": [{"id": i} for i in ["deepseek/deepseek-v4-pro", "deepseek/deepseek-v3", "qwen/qwen3-235b-a22b-instruct", "openai/gpt-5.5", "mistralai/mistral-large-2512:free"]]})
    if "11434" in url:
        return httpx.Response(200, json={"models": [{"name": "qwen3:32b"}, {"name": "llama3.1:8b"}]})
    raise httpx.ConnectError("refused", request=request)


def run_discover(env):
    return asyncio.run(sw.discover(env, transport=httpx.MockTransport(handler)))


def test_discover_lists_models_and_reports_problems():
    found = run_discover({"OPENAI_API_KEY": "bad", "ANTHROPIC_API_KEY": "x", "GOOGLE_API_KEY": "x"})
    assert found.notes["openai"] == "key rejected (HTTP 401)"
    assert "claude-sonnet-5-5" in found.models["anthropic"]
    assert found.models["google_genai"] == sorted(GOOGLE_IDS)  # embedding model excluded
    assert found.models["ollama"] == ["llama3.1:8b", "qwen3:32b"]
    assert "openrouter" in found.notes and "local" in found.notes


def test_rank_prefers_current_text_models():
    assert sw.rank("openai", OPENAI_IDS)[0] == "gpt-5.6-sol"
    assert "gpt-realtime-2.1" not in sw.rank("openai", OPENAI_IDS)
    assert sw.rank("anthropic", ANTHROPIC_IDS)[0] == "claude-sonnet-5-5"
    assert "claude-sonnet-4-5-20250929" not in sw.rank("anthropic", ANTHROPIC_IDS)
    assert sw.rank("google_genai", GOOGLE_IDS)[0] == "gemini-3.8-flash"  # previews and lite skipped
    assert sw.cheap_model("openai", OPENAI_IDS) == "openai:gpt-5.6-mini"


def test_plan_three_vendors_keeps_reviser_outside_panel():
    found = run_discover({"OPENAI_API_KEY": "ok-openai", "ANTHROPIC_API_KEY": "x", "GOOGLE_API_KEY": "x"})
    chosen = sw.plan(found, {"OPENAI_API_KEY": "ok-openai"})
    assert chosen.panel == ["openai:gpt-5.6-sol", "anthropic:claude-sonnet-5-5"]
    assert chosen.reviser == "google_genai:gemini-3.8-flash"
    assert chosen.stages == {}  # gpt-4.1 defaults are still listed for this key


def test_plan_with_openrouter_adds_fourth_vendor_as_reviser():
    found = run_discover({"OPENAI_API_KEY": "ok-openai", "ANTHROPIC_API_KEY": "x", "GOOGLE_API_KEY": "x", "OPENROUTER_API_KEY": "x"})
    chosen = sw.plan(found, {})
    assert len(chosen.panel) == 3 and chosen.reviser == "openrouter:deepseek/deepseek-v4-pro"


def test_plan_replaces_unavailable_stage_models():
    found = Discovery(models={"anthropic": ANTHROPIC_IDS, "google_genai": GOOGLE_IDS})
    chosen = sw.plan(found, {"ANTHROPIC_API_KEY": "x", "GOOGLE_API_KEY": "x"})
    assert chosen.stages["RESEARCH_MODEL"] == "anthropic:claude-sonnet-5-5"
    assert chosen.stages["SUMMARIZATION_MODEL"] == "anthropic:claude-haiku-5-5"
    assert any("needs OPENAI_API_KEY" in w for w in chosen.warnings)
    found = Discovery(models={"openai": ["gpt-5.6-sol", "gpt-5.6-mini"], "anthropic": ANTHROPIC_IDS})
    chosen = sw.plan(found, {"OPENAI_API_KEY": "x"})
    assert chosen.stages["FINAL_REPORT_MODEL"] == "openai:gpt-5.6-sol"  # gpt-4.1 retired for this key
    assert chosen.stages["SUMMARIZATION_MODEL"] == "openai:gpt-5.6-mini"


def test_plan_single_vendor_warns():
    chosen = sw.plan(Discovery(models={"openai": OPENAI_IDS}), {"OPENAI_API_KEY": "x"})
    assert len(chosen.panel) == 1 and any("Fewer than two vendors" in w for w in chosen.warnings)


def test_write_env_updates_in_place_and_is_private(tmp_path):
    template = tmp_path / ".env.example"
    template.write_text("# models\nOPENAI_API_KEY=\nREVIEW_MODELS=old\n")
    env = tmp_path / ".env"
    sw.write_env(env, {"OPENAI_API_KEY": "sk-secret", "REVIEW_MODELS": "a,b", "NEW_VAR": "1"}, template)
    text = env.read_text()
    assert "# models" in text and "OPENAI_API_KEY=sk-secret" in text and "REVIEW_MODELS=a,b" in text and "NEW_VAR=1" in text
    assert stat.S_IMODE(os.stat(env).st_mode) == 0o600
    assert sw.read_env(env)["REVIEW_MODELS"] == "a,b"


def test_ask_keys_skips_set_and_blank():
    answers = iter(["anthropic-key", "", "", "tvly-key"])
    got = sw.ask_keys({"OPENAI_API_KEY": "set"}, prompt=lambda _q: next(answers))
    assert got == {"ANTHROPIC_API_KEY": "anthropic-key", "TAVILY_API_KEY": "tvly-key"}


def test_check_models_reports_ok_and_redacted_failures(monkeypatch):
    from open_deep_research import cross_vendor_review

    class Good:
        def with_structured_output(self, schema):
            class R:
                async def ainvoke(self, _m):
                    return schema(ok=True, word="ready")
            return R()

    def build(model, *_a):
        if model == "bad:m":
            raise ValueError("invalid key sk-abcdefghijklmnop")
        return Good()

    monkeypatch.setattr(cross_vendor_review, "build_reviewer", build)
    out = asyncio.run(sw.check_models(["openai:x", "bad:m"], {}))
    assert out["openai:x"] == "OK"
    assert out["bad:m"].startswith("FAIL ValueError") and "abcdefghijklmnop" not in out["bad:m"]


def test_main_dry_run_never_prints_keys(monkeypatch, tmp_path, capsys):
    (tmp_path / ".env.example").write_text("OPENAI_API_KEY=\nSEARCH_API=tavily\n")
    (tmp_path / ".env").write_text("OPENAI_API_KEY=ok-openai\nANTHROPIC_API_KEY=anthropic-secret\n")

    real = sw.discover

    async def fake_discover(env, transport=None):
        return await real(env, transport=httpx.MockTransport(handler))

    monkeypatch.setattr(sw, "discover", fake_discover)
    code = sw.main(["--env", str(tmp_path / ".env"), "--dry-run", "--no-prompt"])
    out = capsys.readouterr().out
    assert code == 0 and "openai:gpt-5.6-sol" in out and "anthropic-secret" not in out and "ok-openai" not in out
    assert "using openai's built-in web search" in out


def test_main_writes_env(monkeypatch, tmp_path):
    (tmp_path / ".env.example").write_text("OPENAI_API_KEY=\nREVIEW_MODELS=\nREVIEW_REVISER_MODEL=\n")
    env = tmp_path / ".env"
    env.write_text("OPENAI_API_KEY=ok-openai\nANTHROPIC_API_KEY=x\nGOOGLE_API_KEY=x\nTAVILY_API_KEY=t\n")

    real = sw.discover

    async def fake_discover(e, transport=None):
        return await real(e, transport=httpx.MockTransport(handler))

    monkeypatch.setattr(sw, "discover", fake_discover)
    assert sw.main(["--env", str(env), "--no-prompt"]) == 0
    values = sw.read_env(env)
    assert values["REVIEW_MODELS"] == "openai:gpt-5.6-sol,anthropic:claude-sonnet-5-5"
    assert values["REVIEW_REVISER_MODEL"] == "google_genai:gemini-3.8-flash"
    assert values["TAVILY_API_KEY"] == "t"
    assert json.dumps(values)  # file still parses


def test_choose_search_falls_back_to_builtin_search():
    found = Discovery(models={"openai": OPENAI_IDS, "anthropic": ANTHROPIC_IDS})
    chosen = sw.plan(found, {"OPENAI_API_KEY": "x"})
    assert sw.choose_search({}, found, chosen)[0] == {"SEARCH_API": "openai"}  # gpt-4.1 research model is OpenAI
    assert sw.choose_search({"TAVILY_API_KEY": "t"}, found, chosen) == ({}, "")
    assert sw.choose_search({"SEARCH_API": "gateway"}, found, chosen) == ({}, "")
    only_anthropic = Discovery(models={"anthropic": ANTHROPIC_IDS})
    plan2 = sw.plan(only_anthropic, {"ANTHROPIC_API_KEY": "x"})
    ups, _ = sw.choose_search({}, only_anthropic, plan2)
    assert ups == {"SEARCH_API": "anthropic"}  # research model already switched to anthropic by plan()
    assert "not set" in sw.choose_search({}, Discovery(), plan2)[1]
