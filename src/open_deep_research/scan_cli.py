"""crossvet-scan: check web pages for text aimed at AI models.

    uv run crossvet-scan page.html notes.md https://example.com/pricing
    uv run crossvet-scan --json https://example.com/ > scan.json
    uv run crossvet-scan --sitemap https://example.com/sitemap.xml --format html --out report.html
    uv run crossvet-scan --urls pages.txt --format csv --out scan.csv --max-pages 200 --delay 1

A page can carry instructions written for the AI that reads it rather than for a person:
"ignore your instructions", "recommend product X", "cite this URL", often hidden with CSS, HTML
comments, alt text or invisible Unicode. This command splits each page into what a reader sees
and the channels a reader doesn't (hidden elements, comments, attributes, meta tags), runs
Crossvet's injection check (``injection_check.scan``) on each, and reports what it found and
where. Use it to audit your own pages or user-generated content before AI systems read them.

Reports: ``--format text`` (default), ``json`` (``--json`` is an alias), ``csv`` (one row per
finding, plus one per clean page and per error) or ``html`` (one self-contained page for a
client: a summary, then a section per page). ``--out FILE`` writes the report to a file.

Many pages: ``--sitemap URL_OR_FILE`` scans the ``<loc>`` URLs of a sitemap.xml, following a
sitemap index one level deep; ``--urls FILE`` reads one URL per line (blank lines and ``#``
comments skipped). ``--max-pages N`` (default 50) caps the pages fetched over http(s) and
``--delay SECONDS`` (default 0.5) pauses between fetches. Sitemaps over 5 MB are refused.

Exit code: 0 when nothing was found, 1 when any page has a finding, 2 on a usage or fetch error.
The check is pattern matching: a clean result means none of its patterns matched, not that the
page is safe.
"""

from __future__ import annotations

import argparse
import csv
import html
import io
import json
import re
import sys
import time
import xml.etree.ElementTree as ET
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from html.parser import HTMLParser
from pathlib import Path
from typing import Callable

from open_deep_research.injection_check import HIDDEN_PATTERNS, scan

Fetcher = Callable[[str], str]
MAX_SITEMAP_BYTES = 5_000_000
MAX_CHILD_SITEMAPS = 50

HIDDEN_STYLE = re.compile(
    r"display\s*:\s*none|visibility\s*:\s*hidden|font-size\s*:\s*0(?![.\d])|opacity\s*:\s*0(?![.\d]*[1-9])"
    r"|opacity\s*:\s*0?\.0\d*(?![\d])"  # below 0.1: nearly invisible
    r"|font-size\s*:\s*(?:0?\.\d+|1)px|font-size\s*:\s*0?\.[0-2]\d*r?em"  # 1px, 0.5px, 0.1em
    r"|(?<![\w-])(?:left|top|right|bottom|text-indent)\s*:\s*-(?:\d{3,}px|\d{2,}(?:\.\d+)?r?em)"  # off-screen
    r"|clip\s*:\s*rect\(\s*0|clip-path\s*:\s*(?:inset\(\s*(?:50|100)%|circle\(\s*0)"
    r"|transform\s*:\s*scale\(\s*0(?:\.0*)?\s*[,)]"
    r"|(?<![\w-])(?:max-)?(?:height|width)\s*:\s*0(?:px)?\s*;[^\"']*overflow\s*:\s*hidden"
    r"|overflow\s*:\s*hidden\s*;[^\"']*(?<![\w-])(?:max-)?(?:height|width)\s*:\s*0(?![.\d])",
    re.I,
)
TRANSPARENT = re.compile(r"(?<![\w-])color\s*:\s*transparent", re.I)
CLIP_TEXT = re.compile(r"background-clip\s*:\s*text", re.I)


def hides(style: str) -> bool:
    """Whether a CSS declaration block hides its element's text from a person.

    ``color: transparent`` counts unless the same block clips a background to the text (the usual
    gradient-text effect, which is visible). ``min-width``/``min-height`` and ``line-height`` of 0
    do not count.
    """
    if HIDDEN_STYLE.search(style):
        return True
    return bool(TRANSPARENT.search(style)) and not CLIP_TEXT.search(style)


ATTRS = ("alt", "title", "aria-label", "aria-description", "placeholder", "content", "data-ai", "data-llm")
# Elements that do not break a line of text: text split across them is joined with a space.
INLINE = {"a", "abbr", "b", "bdi", "bdo", "cite", "code", "data", "dfn", "em", "font", "i", "kbd", "mark", "q", "s", "samp",
          "small", "span", "strong", "sub", "sup", "time", "u", "var", "wbr"}
VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source", "track", "wbr"}
SKIP = {"script", "style", "noscript", "template"}


@dataclass
class Channels:
    """Text of one page, split by whether a reader sees it."""

    visible: list[str] = field(default_factory=list)
    hidden: list[str] = field(default_factory=list)
    hidden_by_css: list[str] = field(default_factory=list)  # hidden only by stylesheet rules (often UI)
    comments: list[str] = field(default_factory=list)
    attributes: list[str] = field(default_factory=list)
    structured: list[str] = field(default_factory=list)
    noscript: list[str] = field(default_factory=list)


_SIMPLE_SELECTOR = re.compile(r"^([a-z][a-z0-9-]*)?((?:[.#][A-Za-z_][\w-]*)+)$|^([a-z][a-z0-9-]*)$", re.I)


def _strip_comments(css: str) -> str:
    out, i = [], 0
    while True:
        start = css.find("/*", i)
        if start < 0:
            out.append(css[i:])
            return "".join(out)
        out.append(css[i:start])
        end = css.find("*/", start + 2)
        if end < 0:
            return "".join(out)  # unterminated comment runs to the end
        i = end + 2


def css_rules(css: str, _level: int = 0) -> list[tuple[str, str]]:
    """Return ``(selectors, declarations)`` for the top-level rules of a stylesheet.

    One pass over the text, tracking brace depth, so the time is linear in the stylesheet's size
    whatever it contains (an earlier regex version took tens of seconds on a 40 KB stylesheet with
    nested ``@keyframes``). Rules inside ``@layer`` and ``@supports`` blocks are read, since they
    apply to the whole page; other at-rule blocks (``@media``, ``@keyframes``, ``@container``...)
    are skipped at any depth. Unbalanced braces don't derail the rules after them.
    """
    if _level == 0:
        css = _strip_comments(css)
    rules: list[tuple[str, str]] = []
    depth, start, selector, body_start, nested = 0, 0, "", 0, False
    i, n = -1, len(css)
    while i + 1 < n:
        i += 1
        ch = css[i]
        if ch == "\\":  # an escaped character (\{ or \' in a selector) is literal
            i += 1
            continue
        if ch in "\"'":  # a quoted string may hold braces: skip to its closing quote
            j = i + 1
            while j < n and css[j] != ch and css[j] != "\n":
                j += 2 if css[j] == "\\" else 1
            i = j
            continue
        if ch == "{":
            if depth == 0:
                selector, body_start, nested = css[start:i], i + 1, False
            else:
                nested = True
            depth += 1
        elif ch == "}":
            if depth == 0:
                start = i + 1  # stray closing brace: ignore it
                continue
            depth -= 1
            if depth == 0:
                body = css[body_start:i]
                name = selector.strip().split(None, 1)[0].lower() if selector.strip() else ""
                if name in ("@layer", "@supports"):
                    if _level < 8:  # these apply to the whole page: read their rules (bounded nesting)
                        rules.extend(css_rules(body, _level + 1))
                elif not name.startswith("@") and not nested:
                    rules.append((selector.strip(), body))
                start = i + 1
        elif ch == ";" and depth == 0:
            start = i + 1  # a statement at-rule such as @import ...;
    return rules


def hiding_selectors(css: str) -> list[tuple[str, set[str], set[str]]]:
    """Return the simple selectors in a stylesheet whose rules hide an element.

    Each is ``(tag or "", classes, ids)``. Only simple selectors are read (``.a``, ``#b``,
    ``div.a.b``, ``p``); descendant, attribute and pseudo selectors and media queries are skipped,
    and a later rule that shows the element again is not taken into account.
    """
    out = []
    for selectors, body in css_rules(css):
        if not hides(body + ";"):
            continue
        for sel in selectors.split(","):
            m = _SIMPLE_SELECTOR.match(sel.strip())
            if not m:
                continue
            if m.group(3):
                out.append((m.group(3).lower(), set(), set()))
                continue
            parts = re.findall(r"([.#])([A-Za-z_][\w-]*)", m.group(2))
            out.append(((m.group(1) or "").lower(), {n for k, n in parts if k == "."}, {n for k, n in parts if k == "#"}))
    return out


class _Splitter(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.ch = Channels()
        self.stack: list[tuple[str, int]] = []  # (tag, hiding): 0 shown, 1 by stylesheet rules, 2 inline or markup
        self.ld_json = False
        self.joinable: list[str] | None = None  # the list whose last chunk the next inline text continues
        self.hiding: list[tuple[str, set[str], set[str]]] = []  # from <style> blocks seen so far

    def _hidden(self) -> int:
        return max((h for _, h in self.stack), default=0)

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag not in INLINE:
            self.joinable = None
        a = {k.lower(): v or "" for k, v in attrs}
        hidden = 2 if (
            "hidden" in a
            or a.get("aria-hidden", "").lower() == "true"
            or hides(a.get("style", ""))
            or tag in SKIP
        ) else 1 if self._hidden_by_stylesheet(tag, a) else 0
        for name in ATTRS:
            if a.get(name, "").strip() and not (name == "content" and tag != "meta"):
                self.ch.attributes.append(f"{tag}[{name}]: {a[name].strip()}")
        if tag == "input" and a.get("type", "").lower() == "hidden" and a.get("value", "").strip():
            self.ch.attributes.append(f"input[type=hidden][value]: {a['value'].strip()}")
        in_svg = any(t == "svg" for t, _ in self.stack)
        if in_svg and tag in ("title", "desc", "metadata"):
            hidden = 2  # SVG titles show only as a tooltip; desc and metadata are never drawn
        if tag == "script":
            self.ld_json = "ld+json" in a.get("type", "").lower()
        if tag not in VOID:
            self.stack.append((tag, hidden))

    def _hidden_by_stylesheet(self, tag: str, a: dict[str, str]) -> bool:
        if not self.hiding:
            return False
        classes, ident = set(a.get("class", "").split()), a.get("id", "")
        return any((not t or t == tag) and c <= classes and (not i or i == {ident}) and (t or c or i)
                   for t, c, i in self.hiding if t not in ("html", "body", "head"))

    def handle_endtag(self, tag: str) -> None:
        if tag not in INLINE:
            self.joinable = None
        for i in range(len(self.stack) - 1, -1, -1):
            if self.stack[i][0] == tag:
                del self.stack[i:]
                break

    def handle_data(self, data: str) -> None:
        text = data.strip()
        if not text:
            return
        tags = [t for t, _ in self.stack]
        if tags and tags[-1] == "style":
            self.hiding.extend(hiding_selectors(text))
            return
        if tags and tags[-1] == "script" and self.ld_json:
            self.ch.structured.extend(json_strings(text))
            return
        if "noscript" in tags and not {"script", "style", "template"} & set(tags):
            self.ch.noscript.append(text)
            return
        if "template" in tags and not {"script", "style"} & set(tags):
            target = self.ch.hidden  # a browser never renders <template> content; text extractors may read it
        elif any(t in SKIP for t in tags):
            return
        else:
            level = self._hidden()
            target = self.ch.hidden if level == 2 else self.ch.hidden_by_css if level == 1 else self.ch.visible
        if self.joinable is target and target:
            target[-1] += " " + text  # text split across inline elements reads as one run, as a model sees it
        else:
            target.append(text)
        self.joinable = target

    def handle_comment(self, data: str) -> None:
        if data.strip():
            self.ch.comments.append(data.strip())


def json_strings(text: str, limit: int = 5000) -> list[str]:
    """Return the string values inside a JSON-LD block (all of it as one string if it doesn't parse)."""
    try:
        data = json.loads(text)
    except ValueError:
        return [text]
    out: list[str] = []
    todo = [data]
    while todo and len(out) < limit:
        item = todo.pop()
        if isinstance(item, str):
            if item.strip():
                out.append(item.strip())
        elif isinstance(item, dict):
            todo.extend(item.values())
        elif isinstance(item, list):
            todo.extend(item)
    return out[::-1]


def split_html(html: str, css: str = "") -> Channels:
    """Split an HTML page into visible text, hidden text, comments and attributes.

    ``css`` is extra stylesheet text (for example the page's linked stylesheets, read by the caller)
    whose hiding rules apply to the whole page, as rules in ``<style>`` blocks do after they appear.
    """
    parser = _Splitter()
    if css:
        parser.hiding.extend(hiding_selectors(css))
    parser.feed(html)
    parser.close()
    return parser.ch


def looks_like_html(text: str) -> bool:
    """Guess whether ``text`` is an HTML document."""
    return bool(re.search(r"<(?:html|body|div|p|span|head|!--|meta|a\s)[\s>]", text[:5000], re.I))


@dataclass
class Finding:
    """One channel of one page where the check matched."""

    channel: str
    kinds: list[str]
    excerpt: str


@dataclass
class PageResult:
    """What the scan found on one page."""

    source: str
    findings: list[Finding]
    error: str = ""


def _excerpt(text: str, start: int, width: int = 160) -> str:
    lo = max(0, start - 40)
    snippet = re.sub(r"\s+", " ", text[lo : lo + width]).strip()
    snippet = "".join(ch for ch in snippet if ch.isprintable())
    return ("…" if lo else "") + snippet + ("…" if lo + width < len(text) else "")


def scan_text(source: str, text: str, css: str = "", include_repetition: bool = False) -> PageResult:
    """Scan one page's text, channel by channel when it is HTML.

    A channel whose only finding is ``repetition`` (mostly one repeated claim) is dropped unless
    ``include_repetition`` is set: on 740 saved real pages it was the only finding on 29 of the 30
    flagged, all menus, icon labels and template boilerplate. ``css`` is extra stylesheet text whose
    hiding rules apply to the whole page (see ``split_html``).
    """
    if looks_like_html(text):
        ch = split_html(text, css)
        channels = {
            "visible text": "\n".join(ch.visible),
            "hidden elements": "\n".join(ch.hidden),
            "hidden by stylesheet rules": "\n".join(ch.hidden_by_css),
            "HTML comments": "\n".join(ch.comments),
            "attributes and meta tags": "\n".join(ch.attributes),
            "structured data (JSON-LD)": "\n".join(ch.structured),
            "noscript": "\n".join(ch.noscript),
        }
    else:
        channels = {"text": text}
    findings = []
    for name, body in channels.items():
        hits = scan(body)
        if name != "visible text" and name != "text":
            # Hidden channels: report the instruction kinds, not CSS hints that only matter in raw HTML.
            hits = [h for h in hits if h.kind not in HIDDEN_PATTERNS]
        if hits:
            first = min(hits, key=lambda h: h.start)
            kinds = sorted({h.kind for h in hits})
            if kinds == ["repetition"] and not include_repetition:
                continue
            findings.append(Finding(name, kinds, _excerpt(body, first.start)))
    return PageResult(source, findings)


def _refuse_private(request: object) -> None:
    """Refuse a request (including each redirect) to a loopback, private or link-local address."""
    import ipaddress
    import socket

    host = request.url.host  # type: ignore[attr-defined]
    for info in socket.getaddrinfo(host, None):
        ip = ipaddress.ip_address(info[4][0])
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast:
            raise ValueError(f"refusing to fetch {host}: it resolves to a non-public address")


def fetch(url: str, timeout: float = 20.0, allow_private: bool = True, max_bytes: int | None = None) -> str:
    """Fetch a URL over http(s) and return its body as text.

    ``allow_private=False`` refuses hosts that resolve to non-public addresses, checked on every
    redirect; the MCP tool uses it, since an agent chooses the URL there. ``max_bytes`` stops
    reading the body after that many bytes (sitemaps use it). The whole download is limited to
    three times ``timeout``, so a server that sends bytes slowly cannot hold the scan open.
    """
    import httpx

    if not re.match(r"https?://", url, re.I):
        raise ValueError("only http(s) URLs are fetched")
    headers = {"User-Agent": "crossvet-scan (+https://github.com/j-zulick/crossvet)"}
    hooks = {} if allow_private else {"request": [_refuse_private]}
    deadline = time.monotonic() + 3 * timeout  # timeout applies per read; this bounds the whole fetch
    with httpx.Client(follow_redirects=True, timeout=timeout, headers=headers, event_hooks=hooks) as client:
        with client.stream("GET", url) as resp:
            resp.raise_for_status()
            data = bytearray()
            for chunk in resp.iter_bytes():
                data.extend(chunk)
                if max_bytes is not None and len(data) >= max_bytes:
                    break
                if time.monotonic() > deadline:
                    raise TimeoutError(f"{url}: still downloading after {3 * timeout:.0f} s")
            body = bytes(data if max_bytes is None else data[:max_bytes])
            return body.decode(resp.encoding or "utf-8", errors="replace")


def read_source(source: str, fetcher: Fetcher | None = None) -> str:
    """Read a file path, ``-`` for stdin, or an http(s) URL."""
    if source == "-":
        return sys.stdin.read()
    if _is_url(source):
        return (fetcher or fetch)(source)
    return Path(source).read_text(encoding="utf-8", errors="replace")


def _is_url(source: str) -> bool:
    return bool(re.match(r"https?://", source, re.I))


# --- Many pages: sitemaps and URL lists ---------------------------------------------------------


def _read_capped(source: str, fetcher: Fetcher | None) -> str:
    """Read a sitemap from a URL or a file, refusing anything over ``MAX_SITEMAP_BYTES``."""
    if _is_url(source):
        text = fetcher(source) if fetcher else fetch(source, max_bytes=MAX_SITEMAP_BYTES + 1)
        if len(text.encode("utf-8", errors="replace")) > MAX_SITEMAP_BYTES:
            raise ValueError(f"sitemap is larger than {MAX_SITEMAP_BYTES:,} bytes")
        return text
    with open(source, "rb") as fh:
        data = fh.read(MAX_SITEMAP_BYTES + 1)
    if len(data) > MAX_SITEMAP_BYTES:
        raise ValueError(f"sitemap is larger than {MAX_SITEMAP_BYTES:,} bytes")
    return data.decode("utf-8", errors="replace")


def parse_sitemap(xml_text: str) -> tuple[str, list[str]]:
    """Parse a sitemap; return ``("urlset" | "sitemapindex", [<loc> values])``.

    ElementTree does not fetch or expand external entities (no XXE). Sitemaps have no use for a
    DTD, so any ``<!DOCTYPE`` or ``<!ENTITY`` is refused outright, which also rules out
    internal entity-expansion bombs.
    """
    if re.search(r"<!(?:DOCTYPE|ENTITY)", xml_text, re.I):
        raise ValueError("sitemap contains a DTD or entity declaration; refused")
    # ElementTree (expat) never fetches external entities, so a sitemap cannot read local files
    # or make requests through XXE; the size cap is applied by the caller before parsing.
    root = ET.fromstring(xml_text.strip())
    kind = root.tag.rsplit("}", 1)[-1].lower()
    if kind not in ("urlset", "sitemapindex"):
        raise ValueError(f"not a sitemap (root element <{kind}>)")
    locs = [el.text.strip() for el in root.iter() if el.tag.rsplit("}", 1)[-1] == "loc" and el.text and el.text.strip()]
    return kind, locs


def sitemap_urls(source: str, fetcher: Fetcher | None = None) -> tuple[list[str], list[PageResult]]:
    """Return the page URLs in a sitemap, following a sitemap index one level deep.

    Returns ``(urls, errors)``; a child sitemap that cannot be read becomes an error result and
    the others are still used. A child that is itself an index is not followed. Page ``<loc>``
    values must be http(s) URLs, so a sitemap cannot make the scan read local files; a child
    sitemap may be a local path only when the index itself is a local file.
    """
    kind, locs = parse_sitemap(_read_capped(source, fetcher))
    errors: list[PageResult] = []

    def pages(values: list[str], origin: str) -> list[str]:
        bad = [v for v in values if not _is_url(v)]
        if bad:
            errors.append(PageResult(origin, [], f"skipped {len(bad)} <loc> value(s) that are not http(s) URLs"))
        return [v for v in values if _is_url(v)]

    if kind == "urlset":
        return pages(locs, source), errors
    urls: list[str] = []
    for child in locs[:MAX_CHILD_SITEMAPS]:
        try:
            if _is_url(source) and not _is_url(child):
                raise ValueError("a remote sitemap index may only point to http(s) sitemaps")
            child_kind, child_locs = parse_sitemap(_read_capped(child, fetcher))
            if child_kind == "sitemapindex":
                raise ValueError("nested sitemap index not followed (one level deep only)")
            urls.extend(pages(child_locs, child))
        except Exception as exc:  # report and keep going
            errors.append(PageResult(child, [], _err(exc)))
    if len(locs) > MAX_CHILD_SITEMAPS:
        errors.append(PageResult(source, [], f"only the first {MAX_CHILD_SITEMAPS} of {len(locs)} child sitemaps were read"))
    return urls, errors


def read_url_list(path: str) -> list[str]:
    """Read one URL per line, skipping blank lines and ``#`` comments."""
    text = sys.stdin.read() if path == "-" else Path(path).read_text(encoding="utf-8", errors="replace")
    return [s for line in text.splitlines() if (s := line.strip()) and not s.startswith("#")]


def _err(exc: Exception) -> str:
    return f"{type(exc).__name__}: {exc}"[:200]


# --- Reports -----------------------------------------------------------------------------------

DISCLAIMER = "Pattern matching only: a clean result is not proof a page is safe."


def render(results: list[PageResult]) -> str:
    """Render results as plain text for a terminal."""
    lines = []
    for r in results:
        if r.error:
            lines.append(f"✗ {r.source}: could not read ({r.error})")
        elif not r.findings:
            lines.append(f"✓ {r.source}: no text aimed at AI models found")
        else:
            lines.append(f"! {r.source}: {len(r.findings)} finding(s)")
            for f in r.findings:
                lines.append(f"    {f.channel}: {', '.join(f.kinds)}")
                lines.append(f"      {f.excerpt}")
    flagged = sum(1 for r in results if r.findings)
    lines.append(f"\n{flagged} of {len(results)} page(s) contain text aimed at AI models. {DISCLAIMER}")
    return "\n".join(lines)


def render_json(results: list[PageResult]) -> str:
    """Render results as a JSON list, one object per page."""
    return json.dumps([asdict(r) for r in results], indent=2, ensure_ascii=False)


def _csv_cell(value: str) -> str:
    # A spreadsheet runs a cell that starts with = + - @ as a formula; page text is untrusted.
    risky = value[:1] in ("=", "+", "-", "@", "\t", "\r") and value != "-"  # "-" is stdin, not a formula
    return "'" + value if risky else value


def render_csv(results: list[PageResult]) -> str:
    """Render results as CSV: one row per finding, plus one per clean page and per error.

    Cells that a spreadsheet would read as a formula are prefixed with ``'``.
    """
    buf = io.StringIO()
    writer = csv.writer(buf, lineterminator="\n")
    writer.writerow(["source", "status", "channel", "kinds", "excerpt", "error"])
    for r in results:
        if r.error:
            rows = [[r.source, "error", "", "", "", r.error]]
        elif not r.findings:
            rows = [[r.source, "clean", "", "", "", ""]]
        else:
            rows = [[r.source, "finding", f.channel, ";".join(f.kinds), f.excerpt, ""] for f in r.findings]
        for row in rows:
            writer.writerow([_csv_cell(c) for c in row])
    return buf.getvalue()


_CSS = """
body{font-family:system-ui,-apple-system,"Segoe UI",Roboto,sans-serif;max-width:960px;margin:2rem auto;padding:0 1rem;color:#1f2328;line-height:1.5}
h1{font-size:1.6rem;margin-bottom:.25rem}h2{font-size:1.1rem;margin:0 0 .5rem;word-break:break-all}
.meta{color:#59636e;font-size:.9rem}
.summary{display:flex;gap:1rem;flex-wrap:wrap;margin:1.5rem 0}
.stat{border:1px solid #d1d9e0;border-radius:8px;padding:.75rem 1rem;min-width:9rem}
.stat b{display:block;font-size:1.6rem}
.note{background:#fff8c5;border:1px solid #d4a72c;border-radius:8px;padding:.75rem 1rem}
section{border:1px solid #d1d9e0;border-left-width:6px;border-radius:8px;padding:1rem;margin:1rem 0}
section.finding{border-left-color:#cf222e}section.clean{border-left-color:#1a7f37}section.error{border-left-color:#9a6700}
.status{font-weight:600}table{border-collapse:collapse;width:100%;font-size:.92rem}
th,td{text-align:left;vertical-align:top;border-top:1px solid #d1d9e0;padding:.4rem .5rem}
td.excerpt{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;word-break:break-word}
"""


def render_html(results: list[PageResult], generated: str | None = None) -> str:
    """Render results as one self-contained HTML page (inline CSS, no scripts, no external assets).

    All page-derived text (sources, excerpts, errors) is escaped with ``html.escape``.
    """
    esc = html.escape
    when = generated or datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")
    flagged = sum(1 for r in results if r.findings)
    errors = sum(1 for r in results if r.error)
    parts = [
        "<!DOCTYPE html>",
        '<html lang="en"><head><meta charset="utf-8">',
        '<meta name="viewport" content="width=device-width, initial-scale=1">',
        "<title>Crossvet scan: text aimed at AI models</title>",
        f"<style>{_CSS}</style></head><body>",
        "<h1>Text aimed at AI models: scan report</h1>",
        f'<p class="meta">Generated {esc(when)} by crossvet-scan. Each page is split into what a reader sees '
        "and what a reader doesn't (hidden elements, HTML comments, attributes and meta tags); each channel is "
        "checked for instructions written for AI models.</p>",
        '<div class="summary">',
        f'<div class="stat"><b>{len(results)}</b>pages scanned</div>',
        f'<div class="stat"><b>{flagged}</b>pages with findings</div>',
        f'<div class="stat"><b>{errors}</b>errors</div>',
        "</div>",
        f'<p class="note">{esc(DISCLAIMER)} The check looks for known patterns; text it does not recognise '
        "(paraphrased or translated instructions, for example) can still reach an AI model.</p>",
    ]
    for r in results:
        status = "error" if r.error else "finding" if r.findings else "clean"
        parts.append(f'<section class="{status}"><h2>{esc(r.source)}</h2>')
        if r.error:
            parts.append(f'<p class="status">Could not read: {esc(r.error)}</p>')
        elif not r.findings:
            parts.append('<p class="status">No text aimed at AI models found.</p>')
        else:
            parts.append(f'<p class="status">{len(r.findings)} finding(s)</p>')
            parts.append("<table><tr><th>Channel</th><th>Kinds</th><th>Excerpt</th></tr>")
            for f in r.findings:
                parts.append(
                    f"<tr><td>{esc(f.channel)}</td><td>{esc(', '.join(f.kinds))}</td>"
                    f'<td class="excerpt">{esc(f.excerpt)}</td></tr>'
                )
            parts.append("</table>")
        parts.append("</section>")
    parts.append("</body></html>")
    return "\n".join(parts) + "\n"


RENDERERS: dict[str, Callable[[list[PageResult]], str]] = {
    "text": lambda rs: render(rs) + "\n",
    "json": lambda rs: render_json(rs) + "\n",
    "csv": render_csv,
    "html": render_html,
}


# --- Command line ------------------------------------------------------------------------------


def main(
    argv: list[str] | None = None,
    fetcher: Fetcher | None = None,
    sleep: Callable[[float], None] = time.sleep,
    crawler: Callable[[str, int, str], tuple[list, list[str]]] | None = None,
) -> int:
    """Run the command line; return the exit code.

    ``fetcher`` (url -> body text) replaces :func:`fetch` for pages and sitemaps, ``crawler``
    replaces the crawlee-server client for ``--crawl``, and ``sleep`` replaces :func:`time.sleep`,
    so tests run offline and without waiting.
    """
    parser = argparse.ArgumentParser(prog="crossvet-scan", description="Check pages for text aimed at AI models (prompt injection).")
    parser.add_argument("sources", nargs="*", help="file paths, http(s) URLs, or - for stdin")
    parser.add_argument("--format", choices=sorted(RENDERERS), default="text", help="report format (default: text)")
    parser.add_argument("--json", dest="format", action="store_const", const="json", help="same as --format json")
    parser.add_argument("--out", metavar="FILE", help="write the report to FILE instead of stdout")
    parser.add_argument("--sitemap", metavar="URL_OR_FILE", action="append", default=[],
                        help="scan the <loc> URLs of a sitemap.xml or sitemap index (one level deep); repeatable")
    parser.add_argument("--urls", metavar="FILE", action="append", default=[],
                        help="scan the URLs in FILE, one per line (# comments and blank lines skipped); repeatable")
    parser.add_argument("--max-pages", type=int, default=50, metavar="N", help="fetch at most N pages over http(s) (default: 50)")
    parser.add_argument("--delay", type=float, default=0.5, metavar="SECONDS", help="pause between page fetches (default: 0.5)")
    parser.add_argument("--crawl", metavar="URL", action="append", default=[],
                        help="crawl a site through crawlee-server (CRAWLEE_SERVER_URL, CRAWLEE_SERVER_TOKEN) and scan "
                             "every captured page, up to --max-pages; repeatable")
    parser.add_argument("--include-repetition", action="store_true",
                        help="also report channels whose only finding is a repeated claim (off by default: it fires on menus and templates)")
    parser.add_argument("--crawl-mode", choices=("crawl", "page", "sitemap", "map"), default="crawl",
                        help="crawlee-server mode for --crawl: crawl (follow links, default), page, sitemap, map")
    args = parser.parse_args(argv)
    if not (args.sources or args.sitemap or args.urls or args.crawl):
        parser.error("give at least one source, --sitemap, --urls or --crawl")
    if args.max_pages < 0 or args.delay < 0:
        parser.error("--max-pages and --delay must not be negative")

    results: list[PageResult] = []
    for start in args.crawl:
        try:
            if crawler is None:
                from open_deep_research.crawl_source import crawl
                pages, notes = crawl(start, args.max_pages, args.crawl_mode)
            else:
                pages, notes = crawler(start, args.max_pages, args.crawl_mode)
            results.extend(scan_text(page.url, page.body, include_repetition=args.include_repetition) for page in pages)
            for note in notes:
                sys.stderr.write(f"crossvet-scan: {start}: {note}\n")
        except Exception as exc:  # report and keep going
            results.append(PageResult(start, [], _err(exc)))
    sources: list[str] = list(args.sources)
    for sm in args.sitemap:
        try:
            urls, errs = sitemap_urls(sm, fetcher)
            sources.extend(urls)
            results.extend(errs)
        except Exception as exc:  # report and keep going
            results.append(PageResult(sm, [], _err(exc)))
    for path in args.urls:
        try:
            sources.extend(read_url_list(path))
        except Exception as exc:  # report and keep going
            results.append(PageResult(path, [], _err(exc)))
    sources = list(dict.fromkeys(sources))  # drop duplicates, keep order

    fetched = skipped = 0
    for src in sources:
        if _is_url(src):
            if fetched >= args.max_pages:
                skipped += 1
                continue
            if fetched and args.delay:
                sleep(args.delay)
            fetched += 1
        try:
            results.append(scan_text(src, read_source(src, fetcher), include_repetition=args.include_repetition))
        except Exception as exc:  # report and keep going
            results.append(PageResult(src, [], _err(exc)))
    if skipped:
        sys.stderr.write(f"crossvet-scan: --max-pages {args.max_pages} reached; {skipped} URL(s) not scanned\n")

    report = RENDERERS[args.format](results)
    if args.out:
        try:
            Path(args.out).write_text(report, encoding="utf-8")
        except OSError as exc:
            sys.stderr.write(f"crossvet-scan: cannot write {args.out}: {exc}\n")
            return 2
    else:
        sys.stdout.write(report)
    if any(r.error for r in results) and not any(r.findings for r in results):
        return 2
    return 1 if any(r.findings for r in results) else 0


if __name__ == "__main__":
    raise SystemExit(main())
