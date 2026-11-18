"""crossvet-scan: check web pages for text aimed at AI models.

    uv run crossvet-scan page.html notes.md https://example.com/pricing
    uv run crossvet-scan --json https://example.com/ > scan.json

A page can carry instructions written for the AI that reads it rather than for a person:
"ignore your instructions", "recommend product X", "cite this URL", often hidden with CSS, HTML
comments, alt text or invisible Unicode. This command splits each page into what a reader sees
and the channels a reader doesn't (hidden elements, comments, attributes, meta tags), runs
Crossvet's injection check (``injection_check.scan``) on each, and reports what it found and
where. Use it to audit your own pages or user-generated content before AI systems read them.

Exit code: 0 when nothing was found, 1 when any page has a finding, 2 on a usage or fetch error.
The check is pattern matching: a clean result means none of its patterns matched, not that the
page is safe.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import asdict, dataclass, field
from html.parser import HTMLParser
from pathlib import Path

from open_deep_research.injection_check import HIDDEN_PATTERNS, scan

HIDDEN_STYLE = re.compile(
    r"display\s*:\s*none|visibility\s*:\s*hidden|font-size\s*:\s*0(?![.\d])|opacity\s*:\s*0(?![.\d]*[1-9])"
    r"|(?:left|top|text-indent)\s*:\s*-\d{3,}px|clip\s*:\s*rect\(\s*0|height\s*:\s*0(?:px)?\s*;[^\"']*overflow\s*:\s*hidden",
    re.I,
)
ATTRS = ("alt", "title", "aria-label", "aria-description", "placeholder", "content", "data-ai", "data-llm")
VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source", "track", "wbr"}
SKIP = {"script", "style", "noscript", "template"}


@dataclass
class Channels:
    """Text of one page, split by whether a reader sees it."""

    visible: list[str] = field(default_factory=list)
    hidden: list[str] = field(default_factory=list)
    comments: list[str] = field(default_factory=list)
    attributes: list[str] = field(default_factory=list)


class _Splitter(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.ch = Channels()
        self.stack: list[tuple[str, bool]] = []  # (tag, hidden)

    def _hidden(self) -> bool:
        return any(h for _, h in self.stack)

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        a = {k.lower(): v or "" for k, v in attrs}
        hidden = (
            "hidden" in a
            or a.get("aria-hidden", "").lower() == "true"
            or bool(HIDDEN_STYLE.search(a.get("style", "")))
            or tag in SKIP
        )
        for name in ATTRS:
            if a.get(name, "").strip() and not (name == "content" and tag != "meta"):
                self.ch.attributes.append(f"{tag}[{name}]: {a[name].strip()}")
        if tag not in VOID:
            self.stack.append((tag, hidden))

    def handle_endtag(self, tag: str) -> None:
        for i in range(len(self.stack) - 1, -1, -1):
            if self.stack[i][0] == tag:
                del self.stack[i:]
                break

    def handle_data(self, data: str) -> None:
        text = data.strip()
        if not text:
            return
        if any(t in SKIP for t, _ in self.stack):
            return
        (self.ch.hidden if self._hidden() else self.ch.visible).append(text)

    def handle_comment(self, data: str) -> None:
        if data.strip():
            self.ch.comments.append(data.strip())


def split_html(html: str) -> Channels:
    """Split an HTML page into visible text, hidden text, comments and attributes."""
    parser = _Splitter()
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


def scan_text(source: str, text: str) -> PageResult:
    """Scan one page's text, channel by channel when it is HTML."""
    if looks_like_html(text):
        ch = split_html(text)
        channels = {
            "visible text": "\n".join(ch.visible),
            "hidden elements": "\n".join(ch.hidden),
            "HTML comments": "\n".join(ch.comments),
            "attributes and meta tags": "\n".join(ch.attributes),
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
            findings.append(Finding(name, sorted({h.kind for h in hits}), _excerpt(body, first.start)))
    return PageResult(source, findings)


def fetch(url: str, timeout: float = 20.0) -> str:
    """Fetch a URL over http(s) and return its body as text."""
    import httpx

    if not re.match(r"https?://", url, re.I):
        raise ValueError("only http(s) URLs are fetched")
    headers = {"User-Agent": "crossvet-scan (+https://github.com/j-zulick/crossvet)"}
    with httpx.Client(follow_redirects=True, timeout=timeout, headers=headers) as client:
        resp = client.get(url)
        resp.raise_for_status()
        return resp.text


def read_source(source: str) -> str:
    """Read a file path, ``-`` for stdin, or an http(s) URL."""
    if source == "-":
        return sys.stdin.read()
    if re.match(r"https?://", source, re.I):
        return fetch(source)
    return Path(source).read_text(encoding="utf-8", errors="replace")


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
    lines.append(f"\n{flagged} of {len(results)} page(s) contain text aimed at AI models. "
                 "Pattern matching only: a clean result is not proof a page is safe.")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    """Run the command line; return the exit code."""
    parser = argparse.ArgumentParser(prog="crossvet-scan", description="Check pages for text aimed at AI models (prompt injection).")
    parser.add_argument("sources", nargs="+", help="file paths, http(s) URLs, or - for stdin")
    parser.add_argument("--json", action="store_true", help="print results as JSON")
    args = parser.parse_args(argv)
    results = []
    for src in args.sources:
        try:
            results.append(scan_text(src, read_source(src)))
        except Exception as exc:  # report and keep going
            results.append(PageResult(src, [], f"{type(exc).__name__}: {exc}"[:200]))
    if args.json:
        sys.stdout.write(json.dumps([asdict(r) for r in results], indent=2, ensure_ascii=False) + "\n")
    else:
        sys.stdout.write(render(results) + "\n")
    if any(r.error for r in results) and not any(r.findings for r in results):
        return 2
    return 1 if any(r.findings for r in results) else 0


if __name__ == "__main__":
    raise SystemExit(main())
