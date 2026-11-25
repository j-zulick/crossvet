"""Ratings added in Langfuse count here; the weekly report is counted in code."""

from __future__ import annotations

from types import SimpleNamespace as NS

import pytest

from open_deep_research.chat import langfuse_sync, report
from open_deep_research.chat.langfuse_sync import rating_value, sync
from open_deep_research.chat.record import trace_id_for
from open_deep_research.chat.tuning import stats


class FakeScores:
    """Stands in for ``client.api.scores``: pages of scores, the way the Langfuse SDK returns them."""

    def __init__(self, pages):
        self.pages = pages
        self.calls = []

    def get_many(self, **kw):
        self.calls.append(kw)
        index = int(kw.get("cursor") or 0)
        data = self.pages[index] if index < len(self.pages) else []
        nxt = str(index + 1) if index + 1 < len(self.pages) else None
        return NS(data=data, meta=NS(cursor=nxt, limit=kw.get("limit")))


def client_with(*pages):
    return NS(api=NS(scores=FakeScores(list(pages))))


def score(score_id, trace, value, data_type="NUMERIC", source="ANNOTATION", comment=""):
    return NS(id=score_id, name="user-feedback", value=value, data_type=data_type, source=NS(value=source), comment=comment,
              subject=NS(kind="trace", id=trace))


def answer(hub, text="answer"):
    return hub.ask("Fix the race condition in this Go worker pool", slot="strong", author="test")


@pytest.mark.parametrize(("data_type", "value", "expected"), [
    ("NUMERIC", 1, 1.0), ("NUMERIC", 0.7, 1.0), ("NUMERIC", 0.2, 0.0), ("NUMERIC", 4, None),
    ("BOOLEAN", True, 1.0), ("BOOLEAN", False, 0.0),
    ("CATEGORICAL", "Good", 1.0), ("CATEGORICAL", "negative", 0.0), ("CATEGORICAL", "👍", 1.0), ("TEXT", "meh", None),
])
def test_values_read_as_good_or_bad_in_code(data_type, value, expected):
    assert rating_value(data_type, value) == expected


def test_scores_from_langfuse_become_ratings_once(hub):
    first, second = answer(hub), answer(hub)
    t1, t2 = trace_id_for(hub.memory.id, first.turn_id), trace_id_for(hub.memory.id, second.turn_id)
    client = client_with([score("s1", t1, 1, comment="spot on")], [score("s2", t2, "bad", "CATEGORICAL"),
                                                                     score("s3", "unknown-trace", 1)])
    result = sync(hub, client=client)
    assert (result.fetched, result.imported, result.unmatched) == (3, 2, 1)
    saved = {r.turn_id: r for r in hub.memory.ratings(since=0) if r.source.startswith("lf:")}
    assert saved[first.turn_id].value == 1.0 and saved[first.turn_id].comment == "spot on"
    assert saved[second.turn_id].value == 0.0
    again = sync(hub, client=client_with([score("s1", t1, 1)], [score("s2", t2, "bad", "CATEGORICAL")]))
    assert (again.imported, again.already) == (0, 2)


def test_scores_crossvet_sent_itself_are_not_read_back(hub):
    first = answer(hub)
    trace = trace_id_for(hub.memory.id, first.turn_id)
    result = sync(hub, client=client_with([score("s1", trace, 1, source="API")]))
    assert (result.fetched, result.imported) == (1, 0)


def test_unreadable_values_are_reported_not_guessed(hub):
    first = answer(hub)
    trace = trace_id_for(hub.memory.id, first.turn_id)
    result = sync(hub, client=client_with([score("s1", trace, 3)]))
    assert result.unreadable == 1 and result.imported == 0 and "not good or bad" in result.notes[0]


def test_synced_ratings_count_in_tune(hub):
    first = answer(hub)
    sync(hub, client=client_with([score("s1", trace_id_for(hub.memory.id, first.turn_id), 1)]))
    stat = next(iter(stats(hub).values()))
    assert (stat.rated, stat.good) == (1, 1)


def test_sync_asks_for_annotations_under_the_score_name(hub):
    client = client_with([])
    sync(hub, client=client, name="my-score", days=7)
    call = client.api.scores.calls[0]
    assert call["name"] == "my-score" and call["source"] == "ANNOTATION" and call["limit"] == 100


def test_missing_package_or_keys_are_named(monkeypatch):
    from open_deep_research.chat import record

    monkeypatch.setattr(record, "langfuse_installed", lambda: False)
    with pytest.raises(RuntimeError, match="crossvet\\[langfuse\\]"):
        langfuse_sync.default_client()
    monkeypatch.setattr(record, "langfuse_installed", lambda: True)
    monkeypatch.setattr(record, "langfuse_configured", lambda: False)
    with pytest.raises(RuntimeError, match="LANGFUSE_PUBLIC_KEY"):
        langfuse_sync.default_client()


def test_weekly_report_counts_cost_ratings_and_proposals(hub, models):
    from open_deep_research.chat.providers import Reply

    models.set("anthropic:big", Reply(text="a", model="", input_tokens=1000, output_tokens=100, cost=0.01))
    first, second = answer(hub), answer(hub)
    hub.feedback(True, turn_id=first.turn_id)
    hub.feedback(False, turn_id=second.turn_id)
    text = report.weekly(hub, days=7)
    assert "**Answers:** 2; cost known for 2: $0.0200 in all." in text
    assert "**Rated:** 2, of which 1 good (50%)." in text
    assert "| anthropic:big | 2 | $0.0200 | $0.0100 |" in text
    assert "| code | 2 | 2 | 50% | 50% |" in text
    assert "## Proposed changes to the routing table" in text


def test_report_can_be_sent_to_langfuse():
    sent = {}

    class Span:
        trace_id = "t" * 32

        def end(self):
            sent["ended"] = True

    class Client:
        def start_observation(self, **kw):
            sent.update(kw)
            return Span()

        def flush(self):
            sent["flushed"] = True

    assert report.send_to_langfuse("# report", 7, client=Client()) == "t" * 32
    assert sent["name"] == "crossvet-weekly-report" and sent["output"] == "# report" and sent["ended"] and sent["flushed"]
