"""Crossvet: one chat, any model. You pick the model; Crossvet never picks it for you.

Entry points: ``crossvet`` (``cli.py``), an OpenAI-compatible server (``server.py``) and an MCP
server (``mcp_server.py``). Every request goes through ``core.Crossvet``, which guards the call
and logs the turn to one local SQLite file (``store.py``).
"""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("crossvet")
except PackageNotFoundError:  # running from a source tree without an install
    __version__ = "0"
