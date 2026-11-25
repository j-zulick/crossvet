"""Live tests run only with CROSSVET_LIVE=1, so nobody spends money by accident (see live_helpers.py)."""

from __future__ import annotations

import pytest
from live_helpers import have, settings

from crossvet.chat.config import parse
from crossvet.chat.hub import Hub
from crossvet.chat.memory import Memory


@pytest.fixture
def hub(tmp_path):
    """A hub with real providers, a fresh store, and recording to Langfuse when its keys are set."""
    if not (have("openai") or have("anthropic")):
        pytest.skip("needs OPENAI_API_KEY or ANTHROPIC_API_KEY")
    return Hub(parse(settings()), Memory(str(tmp_path / "chat.db")))
