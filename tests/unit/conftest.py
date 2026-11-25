"""Shared test setup: never read or write the user's real model-capability cache."""

import pytest


@pytest.fixture(autouse=True)
def _isolated_capability_cache(monkeypatch, tmp_path):
    try:
        from crossvet import models
    except ImportError:  # the light install (no research extra) runs only the chat tests
        return
    monkeypatch.setattr(models, "CAPABILITY_CACHE", tmp_path / "crossvet-cache" / "openrouter-models.json")
