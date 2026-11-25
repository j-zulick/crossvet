"""Ratings added in Langfuse count in Crossvet, and a weekly report you can read in either place.

``sync`` reads scores people added in Langfuse's interface (source ``ANNOTATION``) under one score
name (``user-feedback`` by default, the name ``/good`` and ``/bad`` use), matches each to the answer
its trace belongs to, and saves it as a rating in the local store, where ``crossvet chat tune``
reads it. Scores Crossvet itself sent (source ``API``) are skipped, and each Langfuse score is
imported once. Only answers saved by this store can be matched, because trace ids are derived
from the store's id and the turn id.

How a score's value becomes good or bad is decided in code:
- numeric: 0 to 1, where 0.5 and above is good; other numbers are not read;
- boolean: true is good;
- categorical or text: "good", "positive", "yes", "up", "1" and the thumbs-up sign are good;
  "bad", "negative", "no", "down", "0" and the thumbs-down sign are bad; anything else is not read.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

from crossvet.chat.record import trace_id_for

if TYPE_CHECKING:
    from crossvet.chat.hub import Hub

GOOD = {"good", "positive", "yes", "up", "1", "true", "👍"}
BAD = {"bad", "negative", "no", "down", "0", "false", "👎"}
PREFIX = "lf:"  # the rating's source: lf:<Langfuse score id>


@dataclass
class SyncResult:
    """What one sync read and saved."""

    fetched: int = 0
    imported: int = 0
    already: int = 0
    unmatched: int = 0
    unreadable: int = 0
    notes: list[str] = field(default_factory=list)

    def summary(self) -> str:
        """Return one line for the terminal."""
        return (f"read {self.fetched} score(s) from Langfuse: {self.imported} new rating(s) saved, "
                f"{self.already} already saved, {self.unmatched} not on an answer in this store, "
                f"{self.unreadable} with a value that is not good or bad")


def rating_value(data_type: str, value: Any) -> float | None:
    """Return 1.0 for good, 0.0 for bad, or ``None`` when the value can't be read as either."""
    kind = str(data_type or "").upper()
    if kind == "BOOLEAN" or isinstance(value, bool):
        return 1.0 if value in (True, 1, "true", "True") else 0.0
    if kind == "NUMERIC" or isinstance(value, (int, float)):
        try:
            number = float(value)
        except (TypeError, ValueError):
            return None
        if not 0.0 <= number <= 1.0:
            return None
        return 1.0 if number >= 0.5 else 0.0
    word = str(value).strip().lower()
    if word in GOOD:
        return 1.0
    if word in BAD:
        return 0.0
    return None


def _trace_of(score: Any) -> str:
    subject = getattr(score, "subject", None)
    if subject is not None:
        if getattr(subject, "kind", "") == "trace":
            return str(getattr(subject, "id", "") or "")
        return str(getattr(subject, "trace_id", "") or "")
    return str(getattr(score, "trace_id", "") or "")


def _source(score: Any) -> str:
    source = getattr(score, "source", "")
    return str(getattr(source, "value", source) or "").upper()


def default_client() -> Any:
    """Return a Langfuse client from the LANGFUSE_* environment, or raise with what to install or set."""
    from crossvet.chat.record import langfuse_configured, langfuse_installed

    if not langfuse_installed():
        raise RuntimeError('the langfuse package is not installed: install crossvet[langfuse]')
    if not langfuse_configured():
        raise RuntimeError("LANGFUSE_PUBLIC_KEY and LANGFUSE_SECRET_KEY are not set")
    from langfuse import get_client

    return get_client()


def sync(hub: Hub, client: Any | None = None, days: float = 30, name: str = "user-feedback",
         sources: tuple[str, ...] = ("ANNOTATION",), page_size: int = 100, max_pages: int = 50) -> SyncResult:
    """Save scores added in Langfuse over the last ``days`` as ratings on the answers they belong to."""
    client = client if client is not None else default_client()
    result = SyncResult()
    since = time.time() - days * 86400
    # answers a little older than the window can still be rated inside it
    traces = {trace_id_for(hub.memory.id, a.id): a.id for a in hub.memory.answers(since=since - 30 * 86400)}
    saved = {r.source for r in hub.memory.ratings(since=0) if r.source.startswith(PREFIX)}
    start = datetime.now(UTC) - timedelta(days=days)
    for source in sources:
        cursor = None
        for _ in range(max_pages):
            page = client.api.scores.get_many(name=name, source=source, from_timestamp=start, limit=page_size,
                                              cursor=cursor)
            for score in getattr(page, "data", []) or []:
                result.fetched += 1
                if _source(score) != source:
                    continue
                tag = (PREFIX + str(getattr(score, "id", "")))[:40]
                if tag in saved:
                    result.already += 1
                    continue
                turn_id = traces.get(_trace_of(score))
                if turn_id is None:
                    result.unmatched += 1
                    continue
                value = rating_value(getattr(score, "data_type", ""), getattr(score, "value", None))
                if value is None:
                    result.unreadable += 1
                    result.notes.append(f"score {getattr(score, 'id', '?')}: value {getattr(score, 'value', None)!r} is not good or bad")
                    continue
                comment = str(getattr(score, "comment", "") or "")
                with hub._lock:
                    hub.memory.add_rating(turn_id, "user-feedback", value, comment, tag)
                saved.add(tag)
                result.imported += 1
            cursor = getattr(getattr(page, "meta", None), "cursor", None)
            if not cursor:
                break
    return result
