"""Load ``.env`` from the folder Crossvet is run in.

``load_dotenv()`` with no path looks for ``.env`` starting from the folder of the calling
module. From a clone that is the repository, so it works; after ``pip install`` or
``uv tool install`` it is the installed package, so a ``.env`` in your working folder was
never read. This module looks from the working folder up first, then falls back to the old
search, so both kinds of install read the same file. Values already set in the environment
win; key values are never printed.
"""

from __future__ import annotations

from dotenv import find_dotenv, load_dotenv


def load_env() -> str:
    """Load the nearest ``.env`` from the working folder up; return its path, or "" if none."""
    path = find_dotenv(usecwd=True) or find_dotenv()
    if path:
        load_dotenv(path)
    return path
