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
            results.extend(scan_text(page.url, page.body) for page in pages)
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
            results.append(scan_text(src, read_source(src, fetcher)))
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
