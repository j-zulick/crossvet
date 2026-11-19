"""The settings reference and .env.example must list every setting in configuration.py."""

import re
from pathlib import Path

from open_deep_research.configuration import Configuration
from open_deep_research.settings_doc import render

ROOT = Path(__file__).resolve().parents[2]


def test_settings_doc_is_generated_from_configuration():
    assert (ROOT / "docs/SETTINGS.md").read_text() == render(), (
        "docs/SETTINGS.md is stale: uv run python -m open_deep_research.settings_doc > docs/SETTINGS.md")


def test_env_example_lists_every_setting():
    example = (ROOT / ".env.example").read_text()
    missing = [n.upper() for n in Configuration.model_fields if not re.search(rf"^{n.upper()}=", example, re.M)]
    assert missing == []


def test_env_example_has_no_secret_values():
    for line in (ROOT / ".env.example").read_text().splitlines():
        name, _, value = line.partition("=")
        if not line.startswith("#") and re.search(r"(KEY|TOKEN|SECRET)$", name):
            assert value in ("", "not-needed"), name
