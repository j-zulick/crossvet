"""Code checks for prompt injection in fetched pages.

A web page can carry text written for the AI that reads it rather than for a
person: "ignore your instructions", "recommend product X", "cite this URL",
often hidden from human readers with CSS or HTML comments. Crossvet's citation
and quote checks cannot catch this, because the injected page really is in the
research notes.

This module is deterministic on purpose (see docs/DESIGN-DECISIONS.md #19): it
scans each page before any model summarizes it, writes a flag line into the
source block of the notes, and lets the review stage list flagged sources and
any report citations that rest on them. It never decides on its own that a page
is false; it marks the page for the reviewers and the reader.

The flag line names only the kinds of pattern found, never the injected text,
so the notes don't carry the instruction on to later models.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

FLAG_PREFIX = "INJECTION CHECK:"

# Instruction-like text aimed at a model. Each pattern is narrow enough that
# ordinary prose about AI (news, research papers) rarely matches it.
_AI = r"(?:ai|a\.i\.|llm|language model|assistant|chatbot|model|agent|gpt|claude|gemini)"
INSTRUCTION_PATTERNS: dict[str, re.Pattern[str]] = {
    "override": re.compile(
        r"\b(?:ignore|disregard|forget|override)\b[^.\n]{0,40}\b(?:previous|prior|above|earlier|all|your|any|system)\b"
        r"[^.\n]{0,20}\b(?:instructions?|prompts?|rules|guidelines|directions)\b",
        re.I,
    ),
    "addressed_to_ai": re.compile(
        rf"\b(?:note|message|instructions?|attention)\s+(?:to|for)\s+(?:any|all|the)?\s*{_AI}s?\b"
        rf"|\bif you are an?\s+{_AI}\b|\bas an?\s+{_AI}\s+(?:reading|summari[sz]ing|processing)\b"
        rf"|\b(?:dear|hey|hello)\s+{_AI}\b",
        re.I,
    ),
    "role_change": re.compile(
        rf"\byou are now\s+(?:an?|the|in)\s+(?:\w+\s+){{0,2}}(?:{_AI}|mode)\b|\bnew instructions?\s*:|\bdeveloper mode\b",
        re.I,
    ),
    "output_steering": re.compile(
        r"\b(?:you must|you should|be sure to|make sure to|please)\s+(?:always\s+)?(?:recommend|cite|mention|link to|rank|say|state)\b"
        r"|\b(?:do not|don't|never)\s+(?:mention|cite|include|report|reveal|disclose)\b[^.\n]{0,40}"
        r"\b(?:summary|report|answer|response|user)\b",
        re.I,
    ),
    "chat_markup": re.compile(
        r"<\|im_(?:start|end)\|>|\[/?INST\]|<\|(?:system|user|assistant)\|>|</?(?:system|webpage_content\w*|untrusted)\b",
        re.I,
    ),
}

# Text hidden from human readers. Only seen when a page's raw HTML is kept.
HIDDEN_PATTERNS: dict[str, re.Pattern[str]] = {
    "hidden_css": re.compile(
        r"display\s*:\s*none|visibility\s*:\s*hidden|font-size\s*:\s*0(?:px|em|rem|pt)?\s*[;\"']"
        r"|opacity\s*:\s*0(?:\.0+)?\s*[;\"']|(?:left|top)\s*:\s*-\d{4,}px",
        re.I,
    ),
    "long_html_comment": re.compile(r"<!--(?:(?!-->)[\s\S]){40,}?-->"),
    "zero_width": re.compile(r"[​‌‍⁠﻿]{3,}"),
}


# Unicode "tag" characters (U+E0000-U+E007F) render as nothing but map one-to-one onto ASCII,
# so a page can carry a whole instruction no reader sees. Emoji flag sequences use a few of them
# legitimately, so only a run long enough to spell words is decoded.
_TAGS = re.compile(r"[\U000E0020-\U000E007E]{8,}")
_BASE64 = re.compile(r"(?<![A-Za-z0-9+/=])[A-Za-z0-9+/]{40,}={0,2}(?![A-Za-z0-9+/=])")


def _decoded_layers(text: str) -> list[tuple[str, str]]:
    """Return (kind, decoded text) for invisible tag-character runs and base64 blobs in ``text``."""
    import base64
    import binascii

    out = [("unicode_tags", "".join(chr(ord(c) - 0xE0000) for c in m.group())) for m in _TAGS.finditer(text)]
    for m in _BASE64.finditer(text):
        blob = m.group()
        try:
            decoded = base64.b64decode(blob + "=" * (-len(blob) % 4), validate=True).decode("utf-8")
        except (binascii.Error, UnicodeDecodeError, ValueError):
            continue
        if decoded.isprintable() or all(ch.isprintable() or ch.isspace() for ch in decoded):
            out.append(("base64", decoded))
    return out


@dataclass(frozen=True)
class Hit:
    """One pattern kind found in a page, with where it first matched."""

    kind: str
    start: int


def scan(text: str) -> list[Hit]:
    """Return one hit per pattern kind found in ``text``.

    Hidden-text patterns count only when the page also contains
    instruction-like text, since hidden elements are common on ordinary pages.
    """
    if not text:
        return []
    hits = [Hit(kind, m.start()) for kind, rx in INSTRUCTION_PATTERNS.items() if (m := rx.search(text))]
    for kind, decoded in _decoded_layers(text):
        inner = [h for h in scan(decoded) if h.kind in INSTRUCTION_PATTERNS]
        if inner:
            hits += [Hit(f"{kind}:{h.kind}", 0) for h in inner]
            hits.append(Hit(kind, 0))
    if hits:
        hits += [Hit(kind, m.start()) for kind, rx in HIDDEN_PATTERNS.items() if (m := rx.search(text))]
    return hits


def flag_line(hits: list[Hit]) -> str:
    """Return the line for a source block of the notes, or "" when clean."""
    if not hits:
        return ""
    kinds = ", ".join(sorted({h.kind for h in hits}))
    return f"{FLAG_PREFIX} instructions aimed at AI models found ({kinds}). Treat this source's claims as unverified."


_SOURCE_RE = re.compile(r"URL:\s*(\S+)[^\n]*\n(?:[^\n]*\n){0,3}?\s*" + re.escape(FLAG_PREFIX))


def flagged_urls(notes: str) -> list[str]:
    """Return URLs of sources whose block in the notes carries a flag line, in order."""
    seen: list[str] = []
    for m in _SOURCE_RE.finditer(notes or ""):
        url = m.group(1).rstrip(").,;")
        if url not in seen:
            seen.append(url)
    return seen


def cited(report: str, urls: list[str]) -> list[str]:
    """Return the URLs from ``urls`` that ``report`` cites, ignoring trailing slashes."""
    found = {u.rstrip("/").rstrip(").,;") for u in re.findall(r"https?://[^\s)\]>\"']+", report or "")}
    return [u for u in urls if u.rstrip("/") in {f.rstrip("/") for f in found}]


_REF_LINE = re.compile(r"^\s*\[(\d+)\][^\n]*?(https?://\S+)\s*$", re.M)
_MARKER = re.compile(r"\[(\d+(?:\s*[,\u2013-]\s*\d+)*)\]")
_SOURCES_HEADING = re.compile(r"^#{1,6}\s*(?:sources|references)\b.*$", re.I | re.M)


def _numbers(marker: str) -> list[int]:
    out: list[int] = []
    for part in re.split(r"\s*,\s*", marker):
        span = re.fullmatch(r"(\d+)\s*[\u2013-]\s*(\d+)", part.strip())
        if span and 0 <= int(span[2]) - int(span[1]) < 50:
            out += list(range(int(span[1]), int(span[2]) + 1))
        elif part.strip().isdigit():
            out.append(int(part))
    return out


def claims_on_flagged(report: str, flagged: list[str]) -> list[str]:
    """Return the report's sentences whose every cited source is one the injection check flagged.

    Citations are read from numbered markers (``[3]``, ``[2][5]``, ``[2, 5]``, ``[2-4]``) resolved
    against the report's numbered source list, and from URLs written into the sentence. A
    sentence that also cites an unflagged source is left alone: another source may support it.
    """
    if not report or not flagged:
        return []
    bad = {u.rstrip("/").rstrip(").,;") for u in flagged}
    refs = {int(n): u.rstrip("/").rstrip(").,;") for n, u in _REF_LINE.findall(report)}
    heading = _SOURCES_HEADING.search(report)
    body = report[: heading.start()] if heading else report
    out: list[str] = []
    for sentence in re.split(r"(?<=[.!?])\s+|\n+", body):
        urls = {refs[n] for m in _MARKER.findall(sentence) for n in _numbers(m) if n in refs}
        urls |= {u.rstrip("/").rstrip(").,;") for u in re.findall(r"https?://[^\s)\]>\"']+", sentence)}
        if urls and urls <= bad:
            text = sentence.strip()
            out.append(text if len(text) <= 300 else text[:297] + "...")
    return out


def neutralize(text: str) -> str:
    """Remove markup that could close the data wrapper or pose as chat roles."""
    text = _TAGS.sub("", text or "")
    return INSTRUCTION_PATTERNS["chat_markup"].sub("[markup removed]", text)
