"""Optional Langfuse tracing.

When LANGFUSE_PUBLIC_KEY and LANGFUSE_SECRET_KEY are set (plus LANGFUSE_BASE_URL for a
self-hosted instance), every model call in a run is traced in Langfuse, which reports
tokens and cost per model. Without those variables tracing is off and nothing is sent.
"""

from __future__ import annotations

import os
from typing import Any


def langfuse_enabled() -> bool:
    """Return True when Langfuse credentials are configured."""
    return bool(os.getenv("LANGFUSE_PUBLIC_KEY") and os.getenv("LANGFUSE_SECRET_KEY"))


def get_callbacks() -> list[Any]:
    """Return LangChain callbacks for the current environment (empty when tracing is off)."""
    if not langfuse_enabled():
        return []
    try:
        from langfuse.langchain import CallbackHandler
    except ImportError:  # optional at runtime; installed by default
        return []
    return [CallbackHandler()]


def flush() -> None:
    """Send buffered traces before the process exits (no-op when tracing is off)."""
    if not langfuse_enabled():
        return
    try:
        from langfuse import get_client

        get_client().flush()
    except Exception:
        pass  # tracing must never break a run
