"""Tests for the configuration pre-flight check."""

import pytest

from open_deep_research import doctor

KEYS = ["OPENAI_API_KEY", "ANTHROPIC_API_KEY", "GOOGLE_API_KEY", "OPENROUTER_API_KEY", "TAVILY_API_KEY",
        "RESEARCH_GATEWAY_URL", "RESEARCH_GATEWAY_TOKEN"]
SETTINGS = ["SEARCH_API", "REVIEW_MODELS", "REVIEW_REVISER_MODEL", "CROSS_VENDOR_REVIEW_ENABLED", "RESEARCH_MODEL",
            "SUMMARIZATION_MODEL", "COMPRESSION_MODEL", "FINAL_REPORT_MODEL"]


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    for k in KEYS + SETTINGS:
        monkeypatch.delenv(k, raising=False)


def levels(findings):
    return [f.level for f in findings]


def test_ready_configuration_has_no_failures(monkeypatch):
    for k in ("OPENAI_API_KEY", "ANTHROPIC_API_KEY", "GOOGLE_API_KEY", "TAVILY_API_KEY"):
        monkeypatch.setenv(k, "x")
    monkeypatch.setenv("CROSS_VENDOR_REVIEW_ENABLED", "true")
    monkeypatch.setenv("REVIEW_MODELS", "openai:a,anthropic:b")
    monkeypatch.setenv("REVIEW_REVISER_MODEL", "google_genai:c")
    findings = doctor.check()
    assert "FAIL" not in levels(findings), findings
    assert any("independent of the panel" in f.message for f in findings)


def test_missing_keys_fail_without_printing_values(monkeypatch, capsys):
    monkeypatch.setenv("CROSS_VENDOR_REVIEW_ENABLED", "true")
    monkeypatch.setenv("REVIEW_MODELS", "openai:a")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-secret-value")
    assert doctor.main() == 1
    printed = capsys.readouterr().out
    assert "TAVILY_API_KEY" in printed and "at least 2 REVIEW_MODELS" in printed
    assert "sk-secret-value" not in printed


def test_single_vendor_panel_and_reviser_conflict_warn(monkeypatch):
    for k in ("OPENAI_API_KEY", "TAVILY_API_KEY"):
        monkeypatch.setenv(k, "x")
    monkeypatch.setenv("CROSS_VENDOR_REVIEW_ENABLED", "true")
    monkeypatch.setenv("REVIEW_MODELS", "openai:a,openai:b")
    msgs = [f.message for f in doctor.check() if f.level == "WARN"]
    assert any("one vendor" in m for m in msgs)
    assert any("shares a vendor" in m for m in msgs)


def test_self_hosted_models_need_no_key(monkeypatch):
    monkeypatch.setenv("TAVILY_API_KEY", "x")
    for s in ("RESEARCH_MODEL", "SUMMARIZATION_MODEL", "COMPRESSION_MODEL", "FINAL_REPORT_MODEL"):
        monkeypatch.setenv(s, "ollama:llama3")
    monkeypatch.setenv("CROSS_VENDOR_REVIEW_ENABLED", "false")
    assert "FAIL" not in levels(doctor.check())


def test_native_search_requires_matching_research_model(monkeypatch):
    monkeypatch.setenv("SEARCH_API", "anthropic")
    monkeypatch.setenv("OPENAI_API_KEY", "x")
    assert any(f.level == "FAIL" and "native anthropic" in f.message for f in doctor.check())


@pytest.mark.parametrize("model,key", [("openai:x", "OPENAI_API_KEY"), ("openrouter:a/b", "OPENROUTER_API_KEY"), ("ollama:x", None), ("local:x", None)])
def test_required_key(model, key):
    assert doctor.required_key(model) == key
