"""Settings: the default model, short names, the menu, prices, and refusing 1.x files."""

from __future__ import annotations

import tomllib

import pytest

from crossvet.config import KNOWN, builtin, load, parse, render
from crossvet.providers import ProviderError

from .conftest import SETTINGS


def test_a_named_model_is_used_as_named():
    cfg = parse(SETTINGS)
    assert cfg.resolve("openai:gpt-6.1-terra") == "openai:gpt-6.1-terra"
    assert cfg.resolve("gpt") == "openai:gpt-6.1-sol"


@pytest.mark.parametrize("name", [None, "", "default", "crossvet", "Default"])
def test_no_name_means_the_default_model(name):
    assert parse(SETTINGS).resolve(name) == "anthropic:claude-sonnet-5-5"


def test_an_unknown_name_is_refused_with_the_short_names_listed():
    with pytest.raises(ValueError, match="unknown model 'gemini'.*claude, gpt, luna, sonnet"):
        parse(SETTINGS).resolve("gemini")
    with pytest.raises(ProviderError):
        parse(SETTINGS).resolve("nope:model")


def test_without_a_default_a_request_must_name_its_model():
    cfg = parse({"models": ["openai:gpt-6-luna"]})
    with pytest.raises(ValueError, match="no model was named"):
        cfg.resolve(None)
    assert cfg.menu() == ["openai:gpt-6-luna"]


def test_a_1x_settings_file_is_refused_with_the_way_forward():
    with pytest.raises(ValueError, match="Crossvet 1.x settings file.*crossvet init"):
        parse({"slots": {"quick": ["openai:gpt-6-luna"]}})


def test_unknown_settings_and_bad_names_are_refused():
    with pytest.raises(ValueError, match="unknown setting"):
        parse({"router": {"use": "rules"}})
    with pytest.raises(ValueError, match=r"unknown \[limits\]"):
        parse({"limits": {"max_usd_per_week": 1}})
    with pytest.raises(ProviderError):
        parse({"names": {"x": "gpt-6"}})
    with pytest.raises(ValueError, match="unknown model"):
        parse({"default_model": "missing"})
    with pytest.raises(ValueError, match="0 or more"):
        parse({"limits": {"max_usd_per_day": -1}})


def test_prices_come_from_the_file_then_the_built_in_table():
    cfg = parse({"prices": {"openrouter:x/y": {"input": 1.0, "output": 3.0}}})
    assert cfg.price("openrouter:x/y") == (1.0, 3.0)
    assert cfg.price("anthropic:claude-opus-5-5") == (4.0, 20.0)
    assert cfg.price("google:unknown") is None
    assert cfg.cost("openai:gpt-6.1-sol", 1_000_000, 100_000) == pytest.approx(3.0)


def test_the_menu_puts_the_default_first_without_repeats():
    assert parse(SETTINGS).menu() == ["anthropic:claude-sonnet-5-5", "anthropic:claude-opus-5-5", "openai:gpt-6.1-sol",
                                      "openai:gpt-6-luna"]


def test_built_in_settings_follow_the_keys_you_have(monkeypatch):
    assert builtin().models == [] and builtin().default_model == ""
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    cfg = builtin()
    assert cfg.default_model == "openai:gpt-6.1-terra"
    assert cfg.names["gpt"] == "openai:gpt-6.1-sol" and "claude" not in cfg.names
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    assert builtin().default_model == "anthropic:claude-sonnet-5-5"
    assert set(builtin().models) == set(KNOWN)


def test_init_output_reads_back_as_the_same_settings(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    cfg = builtin()
    again = parse(tomllib.loads(render(cfg)))
    assert (again.default_model, again.models, again.names) == (cfg.default_model, cfg.models, cfg.names)
    assert again.max_usd_per_day == 5.0 and again.max_usd_per_call == 0.5


def test_the_file_is_found_and_the_env_path_wins(tmp_path, monkeypatch):
    (tmp_path / "crossvet.toml").write_text('default_model = "openai:gpt-6-luna"\n')
    assert load().default_model == "openai:gpt-6-luna"
    other = tmp_path / "other.toml"
    other.write_text('default_model = "anthropic:claude-haiku-5-5"\n')
    monkeypatch.setenv("CROSSVET_CONFIG", str(other))
    assert load().default_model == "anthropic:claude-haiku-5-5"
    monkeypatch.setenv("CROSSVET_CONFIG", str(tmp_path / "missing.toml"))
    with pytest.raises(ValueError, match="does not exist"):
        load()


def test_store_path_follows_the_env(monkeypatch, tmp_path):
    monkeypatch.setenv("CROSSVET_DB", str(tmp_path / "x.db"))
    assert parse({}).store_path() == str(tmp_path / "x.db")
