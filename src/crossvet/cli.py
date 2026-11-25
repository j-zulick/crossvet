"""crossvet: one chat that controls Claude, ChatGPT and other models.

    crossvet chat start      check your keys, print the settings for Hermes and Cursor, and serve
    crossvet chat            chat in this terminal
    crossvet chat --help     every chat command

`crossvet chat ...` is the same as `crossvet-chat ...`.
"""

from __future__ import annotations

import sys


def main(argv: list[str] | None = None) -> int:
    """Entry point: ``crossvet chat ...`` runs the chat; ``--version`` prints the version."""
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv[:1] in (["--version"], ["-V"]):
        from crossvet.chat import __version__

        print(f"crossvet {__version__}")
        return 0
    if argv[:1] == ["chat"]:
        from crossvet.chat.cli import main as chat_main

        return chat_main(argv[1:])
    print(__doc__.strip())
    return 0 if not argv or argv[0] in ("-h", "--help") else 2


if __name__ == "__main__":
    raise SystemExit(main())
