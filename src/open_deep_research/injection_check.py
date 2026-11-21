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
# The same two kinds in Spanish, French, German and Portuguese. Only AI-specific nouns count
# ("inteligencia artificial", "IA", "KI", "modèle de langage", ...), not words that also name
# people ("asistente", "modelo" alone), and an override needs the "previous / system" qualifier,
# so "ignora las instrucciones del fabricante" is ordinary prose and does not match.
_AI_ES = r"(?:(?:modelo|sistema|asistente|agente)s?\s+de\s+(?:inteligencia\s+artificial|ia|lenguaje)|inteligencia\s+artificial|ia|chatbot|llm)"
_AI_FR = r"(?:(?:mod[eè]le|syst[eè]me|assistant|agent)s?\s+(?:de\s+langage|d['’]\s?ia|d['’]\s?intelligence\s+artificielle)|intelligence\s+artificielle|ia|chatbot|llm)"
_AI_DE = r"(?:ki(?:-(?:modell|system|assistent|agent)(?:en|e|s)?)?|k[üu]nstliche[nr]?\s+intelligenz|sprachmodell(?:e|en|s)?|chatbot|llm)"
_AI_PT = r"(?:(?:modelo|sistema|assistente|agente)s?\s+de\s+(?:intelig[êe]ncia\s+artificial|ia|linguagem)|intelig[êe]ncia\s+artificial|ia|chatbot|llm)"
_ADDRESSED_INTL = (
    rf"|\b(?:nota|mensaje|instrucci[oó]n(?:es)?|atenci[oó]n|aviso)\s+(?:para|a|al)\s+(?:cualquier|todo|todos\s+los|todas\s+las|el|la|los|las|un|una)?\s*{_AI_ES}\b"
    rf"|\bsi\s+(?:eres|es|usted\s+es)\s+(?:un|una)\s+{_AI_ES}\b"
    rf"|\b(?:note|message|instructions?|avis)\s+(?:[àa]|pour)\s+(?:toute?s?|tous|les?|la|l['’]|une?)?\s*{_AI_FR}\b"
    rf"|\bsi\s+(?:vous\s+[êe]tes|tu\s+es)\s+(?:un|une)\s+{_AI_FR}\b"
    rf"|\b(?:hinweis|nachricht|notiz|anweisung(?:en)?|achtung)\s+(?:an|f[üu]r)\s+(?:jede[nsr]?|alle|die|den|das|eine?n?)?\s*{_AI_DE}\b"
    rf"|\b(?:wenn|falls)\s+(?:du|sie)\s+(?:eine?\s+)?{_AI_DE}\s+(?:bist|sind)\b"
    rf"|\b(?:nota|mensagem|instru[çc](?:[ãa]o|[õo]es)|aten[çc][ãa]o|aviso)\s+(?:para|a|ao|[àa])\s+(?:qualquer|todo|todos\s+os|todas\s+as|o|a|os|as|um|uma)?\s*{_AI_PT}\b"
    rf"|\bse\s+voc[êe]\s+(?:[ée]|for)\s+(?:um|uma)\s+{_AI_PT}\b"
)
_OVERRIDE_INTL = (
    r"|\b(?:ignora|ignore|ignoren|olvida|olvide|olviden|descarta|descarte|omite|omita)\b[^.\n]{0,30}"
    r"\b(?:instrucciones|indicaciones|reglas|[oó]rdenes)\s+(?:anteriores|previas|originales|del\s+sistema)\b"
    r"|\b(?:ignore[zs]?|oublie[zs]?|ne\s+tiens\s+pas\s+compte|ne\s+tenez\s+pas\s+compte)\b[^.\n]{0,30}"
    r"\b(?:instructions|consignes|r[èe]gles)\s+(?:pr[ée]c[ée]dentes|ant[ée]rieures|initiales|du\s+syst[èe]me|ci-dessus)"
    r"|\b(?:ignoriere|ignoriert|ignorieren\s+sie|vergiss|vergesst|vergessen\s+sie|missachte)\b[^.\n]{0,30}"
    r"\b(?:vorherigen|vorigen|bisherigen|obigen|fr[üu]heren|urspr[üu]nglichen)\s+(?:anweisungen|instruktionen|regeln|vorgaben|befehle)\b"
    r"|\b(?:ignore|ignora|ignorem|esque[çc]a|esque[çc]am|desconsidere|descarte)\b[^.\n]{0,30}"
    r"\b(?:instru[çc][õo]es|regras|orienta[çc][õo]es|ordens)\s+(?:anteriores|pr[ée]vias|originais|do\s+sistema|acima)\b"
)
INSTRUCTION_PATTERNS: dict[str, re.Pattern[str]] = {
    "override": re.compile(
        r"\b(?:ignore|disregard|forget|override)\b[^.\n]{0,40}\b(?:previous|prior|above|earlier|all|your|any|system)\b"
        r"[^.\n]{0,20}\b(?:instructions?|prompts?|rules|guidelines|directions)\b"
        + _OVERRIDE_INTL,
        re.I,
    ),
    "addressed_to_ai": re.compile(
        rf"\b(?:note|message|instructions?|attention)\s+(?:to|for)\s+(?:any|all|the)?\s*{_AI}s?\b"
        rf"|\bif you are an?\s+{_AI}\b|\bas an?\s+{_AI}\s+(?:reading|summari[sz]ing|processing)\b"
        rf"|\b(?:dear|hey|hello)\s+{_AI}\b"
        + _ADDRESSED_INTL,
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


# A "dominant" page repeats one claim or one name until it fills the page, so that a model
# summarizing it treats the claim as established. Two rules, either one flags the page
# (kind "repetition"); both run on visible words only (HTML tags removed; numbers count as words, so
# numbered rows of a table are not "the same sentence"):
#  - repeated sentence: a sentence of at least REPEAT_MIN_SENTENCE_WORDS words occurs at least
#    REPEAT_MIN_COUNT times in the page (also inside longer sentences), and its occurrences make up
#    at least REPEAT_MIN_SHARE of the page's words;
#  - repeated name: one capitalized word (Titlecase, 3+ letters, not a function word) occurs at
#    least NAME_MIN_COUNT times, makes up at least NAME_MIN_SHARE of the page's words, and appears
#    at least once inside a sentence (not first on a line or after a tag), so that labels such as
#    "Price" or "Reply" repeated down a list page don't count as a name.
# Ordinary pages mention their subject far less often: an article that names a company in every
# sentence stays near 5% of its words. A list page whose rows repeat a boilerplate sentence
# ("Free shipping on orders over 50 dollars.") can still trip the first rule.
REPEAT_MIN_SENTENCE_WORDS = 5
REPEAT_MIN_COUNT = 3
REPEAT_MIN_SHARE = 0.30
NAME_MIN_COUNT = 5
NAME_MIN_SHARE = 0.10
_WORD = re.compile(r"[^\W_]+(?:['’-][^\W_]+)*")
_TAG = re.compile(r"<[^>]{0,500}>")
_SENTENCE_BREAK = re.compile(r"[.!?:;|•·\n]+")
_FUNCTION_WORDS = {
    "the", "this", "that", "these", "those", "there", "then", "and", "but", "for", "with", "from", "our",
    "your", "you", "its", "his", "her", "their", "they", "she", "not", "all", "any", "one", "what",
    "when", "where", "which", "who", "how", "why", "yes", "also", "some", "more", "most", "each",
    "el", "la", "los", "las", "les", "der", "die", "das", "und", "une", "des", "por", "para", "con",
}


def repetition(text: str) -> bool:
    """Return True when ``text`` is mostly one repeated sentence or one repeated name (thresholds above)."""
    visible = _TAG.sub("\n", text or "")
    words = _WORD.findall(visible)
    if len(words) < REPEAT_MIN_SENTENCE_WORDS * REPEAT_MIN_COUNT:
        return False
    sentences = [_WORD.findall(part) for part in _SENTENCE_BREAK.split(visible)]
    counts: dict[str, int] = {}
    mid: set[str] = set()
    for sw in sentences:
        for i, w in enumerate(sw):
            if len(w) >= 3 and w[0].isupper() and any(c.islower() for c in w[1:]) and w.lower() not in _FUNCTION_WORDS:
                name = re.sub(r"['’]s$", "", w)
                counts[name] = counts.get(name, 0) + 1
                if i > 0:
                    mid.add(name)
    if any(n >= NAME_MIN_COUNT and n / len(words) >= NAME_MIN_SHARE and name in mid for name, n in counts.items()):
        return True
    lower = [w.lower() for w in words]
    k = REPEAT_MIN_SENTENCE_WORDS
    # Only a sentence whose opening words recur often enough can pass; counting those
    # openings first keeps long pages linear.
    openings: dict[tuple[str, ...], int] = {}
    for i in range(len(lower) - k + 1):
        key = tuple(lower[i : i + k])
        openings[key] = openings.get(key, 0) + 1
    joined = " " + " ".join(lower) + " "
    seen: set[str] = set()
    for sw in sentences:
        sw = [w.lower() for w in sw]
        key = " ".join(sw)
        if len(sw) < k or key in seen or openings.get(tuple(sw[:k]), 0) < REPEAT_MIN_COUNT:
            continue
        seen.add(key)
        n = len(re.findall(rf"(?<= ){re.escape(key)}(?= )", joined))
        if n >= REPEAT_MIN_COUNT and n * len(sw) / len(words) >= REPEAT_MIN_SHARE:
            return True
    return False


@dataclass(frozen=True)
class Hit:
    """One pattern kind found in a page, with where it first matched."""

    kind: str
    start: int


def scan(text: str) -> list[Hit]:
    """Return one hit per pattern kind found in ``text``.

    Hidden-text patterns count only when the page also contains
    instruction-like text, since hidden elements are common on ordinary pages.
    A dominant page (``repetition``, see the thresholds above) counts on its own.
    """
    if not text:
        return []
    hits = [Hit(kind, m.start()) for kind, rx in INSTRUCTION_PATTERNS.items() if (m := rx.search(text))]
    if repetition(text):
        hits.append(Hit("repetition", 0))
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
    if {h.kind for h in hits} == {"repetition"}:
        return f"{FLAG_PREFIX} the page is mostly one repeated claim ({kinds}). Treat this source's claims as unverified."
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


_URL = re.compile(r"https?://[^\s)\]>\"'<]+")
_URL_LINE = re.compile(r"^\s*URL:\s*(\S+)", re.M)


def _norm_url(u: str) -> str:
    """Compare URLs the way a reader would: no scheme, no "www.", no fragment, no trailing slash, no utm_ parameters."""
    from urllib.parse import parse_qsl, urlencode, urlsplit

    parts = urlsplit(u.rstrip(".,;:)"))
    query = urlencode([(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True) if not k.lower().startswith("utm_")])
    return parts.netloc.lower().removeprefix("www.") + parts.path.rstrip("/") + (f"?{query}" if query else "")


def urls_only_in_text(report: str, notes: str) -> list[str]:
    """Return URLs the report cites that the notes contain only inside a source's text.

    The research tools write one block per page, "--- SOURCE n: title ---" followed by
    "URL: <address>". A URL that the notes hold only inside a page's body, never on a
    ``URL:`` line, was written by that page, not found by the search: the research never
    read it, so a citation to it rests on the other page's word. URLs absent from the notes
    altogether are left to the citation check.

    Applied only when the notes contain ``URL:`` lines. Notes in another format (older
    runs, hand-written notes such as "Found at https://...") have no source lines to
    compare with, and every URL in them would be listed by mistake, so they return [].
    """
    sources = {_norm_url(u) for u in _URL_LINE.findall(notes or "")}
    if not sources:
        return []
    in_notes = {_norm_url(u) for u in _URL.findall(notes)}
    out: list[str] = []
    for u in _URL.findall(report or ""):
        u = u.rstrip(".,;:)")
        key = _norm_url(u)
        if key in in_notes and key not in sources and u not in out:
            out.append(u)
    return out


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
