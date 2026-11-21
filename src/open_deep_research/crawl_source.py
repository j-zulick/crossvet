"""Pages from a crawlee-server crawl, for ``crossvet-scan --crawl``.

crawlee-server (an HTTP service around Crawlee, run separately) crawls a site with page capture
on; each stored page is read back from ``/v1/captures/<id>`` and scanned. Settings, read from the
environment so the token stays out of shell history:

    CRAWLEE_SERVER_URL     base URL of the service
    CRAWLEE_SERVER_TOKEN   its bearer token
"""

from __future__ import annotations

import os
import re
from collections.abc import Callable
from dataclasses import dataclass

Post = Callable[[str, dict, dict], dict]   # (url, headers, json body) -> parsed JSON
Get = Callable[[str, dict], str]           # (url, headers) -> body text
CRAWL_MODES = ("crawl", "page", "sitemap", "map")


class CrawlError(RuntimeError):
    """crawlee-server is not configured or answered with an error."""


@dataclass
class CrawledPage:
    """One captured page: its URL and the stored body."""

    url: str
    body: str


def _post(url: str, headers: dict, body: dict, timeout: float = 180.0) -> dict:
    import httpx

    resp = httpx.post(url, headers=headers, json=body, timeout=timeout)
    if resp.status_code >= 400:
        raise CrawlError(f"{url.split('?')[0]} answered HTTP {resp.status_code}")
    return resp.json()


def _get(url: str, headers: dict, timeout: float = 60.0) -> str:
    import httpx

    resp = httpx.get(url, headers=headers, timeout=timeout)
    if resp.status_code >= 400:
        raise CrawlError(f"{url.split('?')[0]} answered HTTP {resp.status_code}")
    return resp.text


def _setting(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise CrawlError(f"{name} is not set")
    return value.rstrip("/") if name.endswith("_URL") else value


def crawl(start_url: str, max_pages: int = 25, mode: str = "crawl", post: Post = _post,
          get: Get = _get) -> tuple[list[CrawledPage], list[str]]:
    """Crawl ``start_url`` through crawlee-server; return the captured pages and notes.

    ``mode`` is crawlee-server's: ``crawl`` follows links, ``page`` fetches only the start URL,
    ``sitemap`` reads the site's sitemap, ``map`` uses its site map. Records without a stored
    capture are counted in the notes, not scanned.
    """
    if not re.match(r"https?://", start_url, re.I):
        raise ValueError("only http(s) URLs are crawled")
    if mode not in CRAWL_MODES:
        raise ValueError(f"mode must be one of {', '.join(CRAWL_MODES)}")
    base, token = _setting("CRAWLEE_SERVER_URL"), _setting("CRAWLEE_SERVER_TOKEN")
    headers = {"authorization": f"Bearer {token}"}
    out = post(f"{base}/v1/crawl", headers,
               {"start_urls": [start_url], "max_pages": max_pages, "capture": True, "mode": mode})
    pages, missing = [], 0
    for rec in out.get("records") or []:
        cid = rec.get("capture_id")
        if not (isinstance(cid, str) and re.fullmatch(r"[0-9a-f]{48}", cid)):
            missing += 1
            continue
        pages.append(CrawledPage(rec.get("listing_url") or rec.get("url") or start_url,
                                 get(f"{base}/v1/captures/{cid}", headers)))
    notes = []
    if out.get("status") not in (None, "ok", "complete", "completed"):
        notes.append(f"crawl status: {out.get('status')}")
    if missing:
        notes.append(f"{missing} record(s) had no stored capture and were not scanned")
    return pages, notes
