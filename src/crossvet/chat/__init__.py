"""Crossvet chat: one chat that routes each request to a suitable model.

The router is code (``classify.py``, ``routing.py``), the guard is code (``hub.py``), and every
turn, its reason and its cost are kept in one local SQLite file (``memory.py``). Entry points:
``crossvet chat`` (``cli.py``), an OpenAI-compatible server (``server.py``) and an MCP server
(``mcp_server.py``).
"""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("crossvet")
except PackageNotFoundError:  # running from a source tree without an install
    __version__ = "0"
