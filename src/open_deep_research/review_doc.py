"""Review an existing report: Crossvet's cross-vendor review outside a research run.

    uv run crossvet review report.md --sources notes.md https://example.com/study --out reviewed.md

    from open_deep_research.api import review
    result = review(open("report.md").read(), ["notes.md", "https://example.com/study"])

The report can come from any tool or person. The sources are what the review checks it against:
files (Markdown, text or HTML) or http(s) URLs. Each source becomes one block of research notes,
with its URL (or file path) and the injection check's flag line when it applies, so every code
check works as in a research run: a cited URL that is not among the sources is flagged, a quote
used as evidence must appear in the sources, and claims resting only on flagged sources go to
*Disputed*. Settings (``REVIEW_MODELS``, the critic, deliberation, the blind pass, Jev) come from
the environment as usual; ``config`` overrides them.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

from open_deep_research.injection_check import flag_line, scan

URL_IN_TEXT = re.compile(r"^\s*(?:url|source)\s*:\s*(https?://\S+)", re.I | re.M)


def _text_of(raw: str) -> str:
    from open_deep_research.scan_cli import looks_like_html, split_html

    if looks_like_html(raw):
        return "\n".join(split_html(raw).visible)
    return raw


def load_source(source: str, fetch: Any = None) -> tuple[str, str, str]:
    """Return (url, title, raw text) for a file path or an http(s) URL.

    A file whose first lines name a ``URL:`` keeps that URL, so a saved page can be cited by its
    web address; otherwise the file is cited by its path.
    """
    if re.match(r"https?://", source, re.I):
        from open_deep_research.scan_cli import fetch as default_fetch

        raw = (fetch or default_fetch)(source)
        title_match = re.search(r"<title[^>]*>(.*?)</title>", raw, re.I | re.S)
        return source, (title_match.group(1).strip() if title_match else source), raw
    path = Path(source)
    raw = path.read_text(encoding="utf-8", errors="replace")
    named = URL_IN_TEXT.search(raw[:2000])
    return (named.group(1) if named else str(path)), path.name, raw


def build_notes(sources: list[str], fetch: Any = None) -> str:
    """Format sources as research notes, one block per source, with injection flags."""
    blocks = []
    for i, src in enumerate(sources, start=1):
        url, title, raw = load_source(src, fetch)
        flag = flag_line(scan(raw))
        text = _text_of(raw).strip()
        blocks.append(f"--- SOURCE {i}: {title} ---\nURL: {url}\n" + (f"{flag}\n" if flag else "") + f"\nCONTENT:\n{text}\n")
    return "\n".join(blocks)


async def areview(report: str, sources: list[str], brief: str = "", config: dict[str, Any] | None = None,
                  fetch: Any = None) -> dict[str, Any]:
    """Review ``report`` against ``sources``; return ``final_report`` and ``review`` as a research run does."""
    from open_deep_research.cross_vendor_review import cross_vendor_review

    if not report or not report.strip():
        raise ValueError("report is empty")
    if not sources:
        raise ValueError("give at least one source to check the report against")
    notes = build_notes(sources, fetch)
    state = {"final_report": report, "raw_notes": [notes], "research_brief": brief or "Review this report against its sources."}
    # Environment variables take precedence over ``configurable``, so overrides are applied there.
    overrides = {"CROSS_VENDOR_REVIEW_ENABLED": "true", **{k.upper(): str(v) for k, v in (config or {}).items()}}
    saved = {k: os.environ.get(k) for k in overrides}
    os.environ.update(overrides)
    try:
        out = await cross_vendor_review(state, {"configurable": {}})
    finally:
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
    if not out:
        raise RuntimeError("review did not run: set REVIEW_MODELS to at least two models (crossvet-doctor checks this)")
    return {**out, "raw_notes": [notes]}
