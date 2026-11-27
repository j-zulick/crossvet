"""Copy turns, routing decisions and ratings to Langfuse (optional), and read back ratings added there.

    crossvet sync            sends what is new since the last sync; prints what it sent

Keys come from ``LANGFUSE_PUBLIC_KEY``, ``LANGFUSE_SECRET_KEY`` and ``LANGFUSE_BASE_URL`` (default
https://us.cloud.langfuse.com). Each answer becomes a trace (question, answer, model, tokens, cost,
and Crossvet's decision when it chose); each rating a score named ``user_rating`` (+1 or -1); each
judge's score (``crossvet score run``) a score named ``judge_score`` (1 to 5).
Nothing is sent unless you run ``sync``, and the local files stay the record: Langfuse is a copy.

Langfuse v4 (Langfuse Cloud since 2026-11-16) takes traces only over OpenTelemetry: each answer goes to
``/api/public/otel/v1/traces`` as one OTLP/HTTP JSON span of type ``generation``. Scores still go to
``/api/public/ingestion`` as ``score-create`` events, which v4 keeps, and ratings added in Langfuse are read
from ``/api/public/v3/scores``.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
import uuid
from typing import TYPE_CHECKING, Any

import httpx

if TYPE_CHECKING:
    from crossvet.core import Crossvet

BATCH = 50


def configured() -> bool:
    """Whether both Langfuse keys are set."""
    return bool(os.environ.get("LANGFUSE_PUBLIC_KEY") and os.environ.get("LANGFUSE_SECRET_KEY"))


def _client(transport: httpx.BaseTransport | None) -> httpx.Client:
    base = os.environ.get("LANGFUSE_BASE_URL") or "https://us.cloud.langfuse.com"
    auth = (os.environ.get("LANGFUSE_PUBLIC_KEY", ""), os.environ.get("LANGFUSE_SECRET_KEY", ""))
    return httpx.Client(base_url=base.rstrip("/"), auth=auth, timeout=30.0, transport=transport)


def trace_id(cv: Crossvet, turn_id: int) -> str:
    """Return a stable Langfuse trace id for a turn (the same turn always maps to the same trace)."""
    seed = cv.lab.get("langfuse_seed")
    if not seed:
        seed = uuid.uuid4().hex
        cv.lab.put("langfuse_seed", seed)
    return uuid.uuid5(uuid.NAMESPACE_URL, f"crossvet:{seed}:{turn_id}").hex


def _attr(key: str, value: Any) -> dict[str, Any]:
    if isinstance(value, list):
        return {"key": key, "value": {"arrayValue": {"values": [{"stringValue": str(v)} for v in value]}}}
    return {"key": key, "value": {"stringValue": value if isinstance(value, str) else json.dumps(value)}}


def spans(cv: Crossvet, after_turn: int) -> tuple[list[dict[str, Any]], int]:
    """Return one OTLP span per answer after the cursor, and the new cursor."""
    out: list[dict[str, Any]] = []
    rows = cv.store.db.execute("SELECT a.*, q.content question FROM turns a LEFT JOIN turns q ON q.thread = a.thread "
                               "AND q.id = a.id - 1 AND q.role = 'user' WHERE a.role = 'assistant' AND a.id > ? "
                               "ORDER BY a.id LIMIT 500", (after_turn,)).fetchall()
    last_turn = after_turn
    for row in rows:
        meta = json.loads(row["meta"] or "{}")
        decision = cv.lab.decision(turn_id=row["id"])
        tid = trace_id(cv, row["id"])
        start = int(float(row["ts"]) * 1e9)
        end = start + int(float(meta.get("seconds") or 0) * 1e9)
        attrs = [_attr("langfuse.trace.name", f"crossvet/{row['author']}"),
                 _attr("langfuse.observation.type", "generation"),
                 _attr("langfuse.observation.input", row["question"] or ""),
                 _attr("langfuse.observation.output", row["content"]),
                 _attr("langfuse.observation.model.name", row["model"]),
                 _attr("langfuse.observation.usage_details",
                       {"input": int(meta.get("input_tokens") or 0), "output": int(meta.get("output_tokens") or 0)}),
                 _attr("langfuse.session.id", str(row["thread"])),
                 _attr("langfuse.trace.tags", ["crossvet"]),
                 _attr("langfuse.trace.metadata.turn", str(row["id"])),
                 _attr("langfuse.trace.metadata.app", row["author"])]
        if row["cost"] is not None:
            attrs.append(_attr("langfuse.observation.cost_details", {"total": row["cost"]}))
        if decision:
            attrs.append(_attr("langfuse.trace.metadata.decision", decision))
        out.append({"traceId": tid, "spanId": hashlib.sha256(tid.encode()).hexdigest()[:16], "name": "answer", "kind": 1,
                    "startTimeUnixNano": str(start), "endTimeUnixNano": str(max(end, start)), "attributes": attrs})
        last_turn = row["id"]
    return out, last_turn


def events(cv: Crossvet, after_rating: int) -> tuple[list[dict[str, Any]], int]:
    """Return the score-create events for ratings and judge scores after the cursors, and the new rating cursor."""
    out: list[dict[str, Any]] = []
    trace_id(cv, 0)  # makes sure this install has its seed
    mine = cv.lab.get("langfuse_seed")[:12]  # score ids are upserted in Langfuse, so they must differ between installs
    ratings = cv.lab.db.execute("SELECT * FROM ratings WHERE id > ? AND source != 'langfuse' ORDER BY id LIMIT 500",
                                (after_rating,)).fetchall()
    last_rating = after_rating
    for rating in ratings:
        stamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(rating["ts"]))
        out.append({"id": uuid.uuid4().hex, "type": "score-create", "timestamp": stamp,
                    "body": {"id": f"crossvet-rating-{mine}-{rating['id']}", "traceId": trace_id(cv, rating["turn_id"]),
                             "name": "user_rating", "value": rating["rating"], "comment": rating["note"] or None}})
        last_rating = rating["id"]
    after_score = int(cv.lab.get("langfuse_score", "0"))
    for score in cv.lab.db.execute("SELECT * FROM scores WHERE id > ? AND score IS NOT NULL ORDER BY id LIMIT 500",
                                   (after_score,)).fetchall():
        stamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(score["ts"]))
        out.append({"id": uuid.uuid4().hex, "type": "score-create", "timestamp": stamp,
                    "body": {"id": f"crossvet-judge-{mine}-{score['id']}", "traceId": trace_id(cv, score["turn_id"]),
                             "name": "judge_score", "value": score["score"], "comment": f"{score['judge']}: {score['why']}"}})
        cv.lab.put("langfuse_score_pending", str(score["id"]))
    return out, last_rating


def _refused(what: str, response: httpx.Response) -> RuntimeError:
    return RuntimeError(f"Langfuse answered HTTP {response.status_code} to {what}: {response.text[:200]}; nothing more was sent")


def sync(cv: Crossvet, transport: httpx.BaseTransport | None = None) -> str:
    """Send new turns and ratings to Langfuse and read back ratings added there; return a summary."""
    if not configured():
        return "Langfuse is not set up: add LANGFUSE_PUBLIC_KEY and LANGFUSE_SECRET_KEY (see .env.example). Nothing was sent."
    after_turn, after_rating = int(cv.lab.get("langfuse_turn", "0")), int(cv.lab.get("langfuse_rating", "0"))
    traces, last_turn = spans(cv, after_turn)
    scores, last_rating = events(cv, after_rating)
    with _client(transport) as client:
        for start in range(0, len(traces), BATCH):
            body = {"resourceSpans": [{"resource": {"attributes": [_attr("service.name", "crossvet")]},
                                       "scopeSpans": [{"scope": {"name": "crossvet"}, "spans": traces[start:start + BATCH]}]}]}
            response = client.post("/api/public/otel/v1/traces", json=body, headers={"x-langfuse-ingestion-version": "4"})
            if response.status_code not in (200, 202):
                raise _refused("the traces", response)
        if traces:
            cv.lab.put("langfuse_turn", str(last_turn))
        for start in range(0, len(scores), BATCH):
            response = client.post("/api/public/ingestion", json={"batch": scores[start:start + BATCH]})
            if response.status_code not in (200, 207):
                raise _refused("the scores", response)
            errors = (response.json() or {}).get("errors") or []
            if errors:
                raise RuntimeError(f"Langfuse refused {len(errors)} score(s): {str(errors[0])[:200]}")
        cv.lab.put("langfuse_rating", str(last_rating))
        cv.lab.put("langfuse_score", cv.lab.get("langfuse_score_pending", cv.lab.get("langfuse_score", "0")))
        pulled = pull_ratings(cv, client)
    return (f"Sent {len(traces)} answer(s) and {len(scores)} score(s) to Langfuse (answers up to turn #{last_turn}, "
            f"ratings up to #{last_rating}); read back {pulled} rating(s) added in Langfuse.")


def pull_ratings(cv: Crossvet, client: httpx.Client) -> int:
    """Copy ``user_rating`` scores added in Langfuse (not by Crossvet) into the lab file; return how many."""
    seen = set(json.loads(cv.lab.get("langfuse_pulled", "[]")))
    response = client.get("/api/public/v3/scores", params={"name": "user_rating", "limit": 100, "fields": "subject"})
    if response.status_code != 200:
        return 0
    turns = {trace_id(cv, r["turn_id"]): r["turn_id"] for r in cv.lab.db.execute("SELECT turn_id FROM decisions").fetchall()}
    turns.update({trace_id(cv, r["id"]): r["id"] for r in cv.store.db.execute(
        "SELECT id FROM turns WHERE role='assistant' ORDER BY id DESC LIMIT 2000").fetchall()})
    added = 0
    for score in (response.json() or {}).get("data") or []:
        subject = score.get("subject") or {}
        trace = subject.get("id") if subject.get("kind") == "trace" else score.get("traceId")
        sid, value = str(score.get("id", "")), score.get("value")
        if sid.startswith("crossvet-") or sid in seen or trace not in turns or value not in (1, -1, 1.0, -1.0):
            continue
        cv.lab.rate(turns[trace], int(value), str(score.get("comment") or ""), source="langfuse")
        seen.add(sid)
        added += 1
    cv.lab.put("langfuse_pulled", json.dumps(sorted(seen)[-5000:]))
    return added
