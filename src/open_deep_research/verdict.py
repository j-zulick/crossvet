"""The one-line verdict that opens every Review notes section, counted in code.

Kept apart from the review stage so the offline demo can show it without the research
dependencies installed.
"""

from __future__ import annotations


def verdict_line(flagged_urls: list[str], text_only: list[str], injected: list[str], disputed: list[dict], dissent: list[str],
                 failed: list[str], revision_error: str = "") -> str:
    """Return the first line of the Review notes: one verdict from the checks, counted in code."""
    problems = [(len(flagged_urls), "citation(s) not found in the research notes"),
                (len(text_only), "cited URL(s) found only inside another page's text"),
                (len(injected), "source(s) flagged by the injection check"),
                (len(disputed), "finding(s) disputed"),
                (len(dissent), "reviewer point(s) of dissent"),
                (len(failed), "reviewer(s) failed"),
                (1 if revision_error else 0, "revision failed")]
    found = [f"{n} {what}" for n, what in problems if n]
    if not found:
        return "**Verdict: no problems found by the checks.** Citations match the notes and nothing was disputed; this is not proof the report is right."
    return "**Verdict: check before relying on it.** " + "; ".join(found) + " (details below)."
