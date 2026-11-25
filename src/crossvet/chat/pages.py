"""Read posts and pages for `crossvet chat routes import`, checked for text aimed at AI models.

Each post is fetched, HTML is split into what a reader sees and what is hidden, and every part is
checked before a model reads it.

Hidden channels (CSS-hidden elements, comments, attributes, meta tags, invisible Unicode) are
checked with ``crossvet.injection_check``; a post with a finding is refused, not summarized. The
check is pattern matching: a clean result means none of its patterns matched, not that the text is
safe.
"""

from __future__ import annotations

import json
import re
import sys
import time
from dataclasses import dataclass, field
from html.parser import HTMLParser
from pathlib import Path
from typing import Callable

from crossvet.injection_check import HIDDEN_PATTERNS, scan

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
    opinions: dict[str, dict] = field(default_factory=dict)  # second opinions (--second-opinion), beside the finding


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
    ``include_repetition`` is set: on 608 real pages it was the only finding on 23 of the 24 flagged,
    all menus, icon labels and template boilerplate.
    ``css`` is extra stylesheet text whose
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
    return scan_channels(source, channels, include_repetition)


def scan_channels(source: str, channels: dict[str, str], include_repetition: bool = False) -> PageResult:
    """Scan named channels of one source; "visible text", "text" and "PDF text" are what a reader sees."""
    findings = []
    for name, body in channels.items():
        hits = scan(body)
        if name not in ("visible text", "text", "PDF text"):
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
    headers = {"User-Agent": "crossvet (+https://github.com/j-zulick/crossvet)"}
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
