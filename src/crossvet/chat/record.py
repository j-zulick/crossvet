"""Record every turn and every rating, locally and in Langfuse (or a JSON-lines file).

The local store (``memory.py``) is the source of truth: turns and ratings are written there
first. Sinks get a copy, best effort, and a failing sink never breaks a turn.

What is recorded for each answer: the model (and the model a hosted router picked), the kind
of task, difficulty, slot, router, the reason in words, every attempt, tokens, cost, seconds,
and whether the guard escalated. With ``content = "metadata"`` the request and answer text are
left out of the sinks (the local store still keeps them).

Ratings, all stored as scores on the answer's trace:

    user-feedback   1 good, 0 bad (/good, /bad, ``crossvet chat feedback``, POST /api/feedback)
    retried         1: the user asked the same question again (/retry)
    switched        1: the user picked another model for the next turn
    escalated       1 or 0, set when the answer is recorded: the first model failed a check

A turn's trace id is derived from its id and the store's own id, so a rating given later, from
another process or app, lands on the same trace.

With ``OTEL_EXPORTER_OTLP_ENDPOINT`` set (and the ``otel`` extra), each turn is also sent as an
OpenTelemetry span with the standard GenAI attributes (``gen_ai.*``), never with its text.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import time
from contextlib import nullcontext
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable, Protocol

SCORES = ("user-feedback", "retried", "switched", "escalated")
CONTENT = ("full", "metadata")
SINKS = ("auto", "langfuse", "jsonl", "off")


@dataclass
class TurnRecord:
    """One answered request, as sent to a sink."""

    trace_id: str
    turn_id: int
    thread: str
    app: str
    model: str
    kind: str
    difficulty: int
    slot: str
    why: str
    router: str = "rules"
    served_by: str = ""
    prompt: str | None = None
    answer: str | None = None
    attempts: list[dict[str, Any]] = field(default_factory=list)
    cost: float | None = None
    input_tokens: int = 0
    output_tokens: int = 0
    seconds: float = 0.0
    escalated: bool = False
    tools: bool = False
    explored: bool = False
    ts: float = field(default_factory=time.time)


class Sink(Protocol):
    """Somewhere turns and scores are copied to."""

    def turn(self, record: TurnRecord) -> None:  # pragma: no cover - protocol
        """Record one answered request."""

    def score(self, trace_id: str, name: str, value: float, comment: str = "") -> None:  # pragma: no cover - protocol
        """Attach a score to a turn's trace."""

    def flush(self) -> None:  # pragma: no cover - protocol
        """Send anything buffered."""


def trace_id_for(store_id: str, turn_id: int) -> str:
    """Return the turn's trace id: 32 lowercase hex characters (the W3C format Langfuse uses)."""
    return hashlib.sha256(f"crossvet-chat:{store_id}:{turn_id}".encode()).hexdigest()[:32]


class LangfuseSink:
    """Copy turns and scores to Langfuse: one generation per answer, the thread as the session."""

    def __init__(self, client: Any | None = None, propagate: Callable[..., Any] | None = None) -> None:
        """Use ``client`` (a Langfuse client) or build one from the LANGFUSE_* environment."""
        if client is None:
            from langfuse import get_client

            client = get_client()
        if propagate is None:
            try:
                from langfuse import propagate_attributes as propagate
            except ImportError:  # older SDKs: no session grouping
                propagate = None
        self.client = client
        self.propagate = propagate

    def turn(self, record: TurnRecord) -> None:
        """Record one answer as a generation on its own trace."""
        tags = [f"kind:{record.kind}", f"slot:{record.slot}", f"router:{record.router}"]
        if record.escalated:
            tags.append("escalated")
        scope = self.propagate(session_id=record.thread, user_id=record.app, tags=tags, trace_name="crossvet-chat") \
            if self.propagate else nullcontext()
        metadata = {k: v for k, v in asdict(record).items() if k not in ("prompt", "answer", "trace_id", "model")}
        with scope:
            generation = self.client.start_observation(
                trace_context={"trace_id": record.trace_id}, name="crossvet-chat", as_type="generation",
                model=record.served_by or record.model, input=record.prompt, output=record.answer, metadata=metadata,
                usage_details={"input": record.input_tokens, "output": record.output_tokens},
                cost_details={"total": record.cost} if record.cost is not None else None)
            generation.end()
        self.score(record.trace_id, "escalated", 1.0 if record.escalated else 0.0)

    def score(self, trace_id: str, name: str, value: float, comment: str = "") -> None:
        """Attach a score to a trace."""
        kind = "BOOLEAN" if name in SCORES else "NUMERIC"
        self.client.create_score(trace_id=trace_id, name=name, value=float(value), data_type=kind, comment=comment or None)

    def flush(self) -> None:
        """Send buffered events."""
        self.client.flush()


class OtelSink:
    """Each turn as an OpenTelemetry span with the standard GenAI attributes, for any OTLP backend.

    On when ``OTEL_EXPORTER_OTLP_ENDPOINT`` (or ``OTEL_EXPORTER_OTLP_TRACES_ENDPOINT``) is set and the
    ``otel`` extra is installed. Text is never put on a span; scores become span events.
    ``tracer`` replaces the OTLP exporter's tracer in tests.
    """

    def __init__(self, tracer: Any = None) -> None:  # noqa: D107
        if tracer is None:
            from opentelemetry.exporter.otlp.proto.http.trace_exporter import (
                OTLPSpanExporter,
            )
            from opentelemetry.sdk.resources import Resource
            from opentelemetry.sdk.trace import TracerProvider
            from opentelemetry.sdk.trace.export import BatchSpanProcessor

            provider = TracerProvider(resource=Resource.create({"service.name": "crossvet-chat"}))
            provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter()))
            tracer = provider.get_tracer("crossvet.chat")
        self.tracer = tracer

    def turn(self, record: TurnRecord) -> None:  # noqa: D102
        provider, _, model = (record.served_by or record.model).partition(":")
        with self.tracer.start_as_current_span(f"chat {model or record.model}") as span:
            for key, value in {
                "gen_ai.operation.name": "chat", "gen_ai.system": provider, "gen_ai.request.model": record.model,
                "gen_ai.response.model": record.served_by or record.model, "gen_ai.usage.input_tokens": record.input_tokens,
                "gen_ai.usage.output_tokens": record.output_tokens, "crossvet.trace_id": record.trace_id,
                "crossvet.turn_id": record.turn_id, "crossvet.kind": record.kind, "crossvet.difficulty": record.difficulty,
                "crossvet.slot": record.slot, "crossvet.router": record.router, "crossvet.escalated": record.escalated,
                "crossvet.attempts": len(record.attempts), "crossvet.seconds": record.seconds,
            }.items():
                span.set_attribute(key, value)
            if record.cost is not None:
                span.set_attribute("crossvet.cost_usd", record.cost)

    def score(self, trace_id: str, name: str, value: float, comment: str = "") -> None:  # noqa: D102
        with self.tracer.start_as_current_span("crossvet.score") as span:
            span.set_attribute("crossvet.trace_id", trace_id)
            span.add_event(name, {"value": value})


def otel_configured() -> bool:
    """Whether an OTLP endpoint is set in the environment."""
    return bool(os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT") or os.environ.get("OTEL_EXPORTER_OTLP_TRACES_ENDPOINT"))


class JsonlSink:
    """Append turns and scores to a JSON-lines file, for any other tool to read."""

    def __init__(self, path: str) -> None:
        """Write to ``path`` (its folder is created)."""
        self.path = Path(os.path.expanduser(path))
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def _write(self, row: dict[str, Any]) -> None:
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(row, default=str) + "\n")

    def turn(self, record: TurnRecord) -> None:
        """Append one turn."""
        self._write({"type": "turn", **asdict(record)})

    def score(self, trace_id: str, name: str, value: float, comment: str = "") -> None:
        """Append one score."""
        self._write({"type": "score", "trace_id": trace_id, "name": name, "value": value, "comment": comment, "ts": time.time()})

    def flush(self) -> None:
        """Nothing is buffered."""


class Recorder:
    """Writes ratings to the local store and copies turns and ratings to the sinks."""

    def __init__(self, sinks: list[Sink] | None = None, content: str = "full") -> None:
        """Copy to ``sinks``; ``content="metadata"`` leaves the request and answer text out of them."""
        if content not in CONTENT:
            raise ValueError(f"record content must be one of {', '.join(CONTENT)}")
        self.sinks = list(sinks or [])
        self.content = content
        self.errors: list[str] = []

    def _each(self, action: Callable[[Sink], None]) -> None:
        for sink in self.sinks:
            try:
                action(sink)
            except Exception as exc:  # noqa: BLE001  a sink must never break a turn
                self.errors.append(f"{type(sink).__name__}: {exc}"[:200])

    def turn(self, record: TurnRecord) -> None:
        """Copy one answered request to every sink."""
        if self.content == "metadata":
            record.prompt, record.answer = None, None
        self._each(lambda sink: sink.turn(record))

    def score(self, trace_id: str, name: str, value: float, comment: str = "") -> None:
        """Copy one score to every sink."""
        self._each(lambda sink: sink.score(trace_id, name, value, "" if self.content == "metadata" else comment))

    def flush(self) -> None:
        """Flush every sink."""
        self._each(lambda sink: sink.flush())


def langfuse_configured() -> bool:
    """Return whether Langfuse keys are in the environment."""
    return bool(os.environ.get("LANGFUSE_PUBLIC_KEY") and os.environ.get("LANGFUSE_SECRET_KEY"))


def build(sink: str = "auto", content: str = "full", jsonl: str = "") -> Recorder:
    """Return the recorder the settings ask for.

    ``auto`` copies to Langfuse when its keys are set, and to ``jsonl`` when a path is given;
    ``langfuse`` requires the keys; ``off`` copies nowhere (the local store still keeps everything).
    """
    if sink not in SINKS:
        raise ValueError(f"record sink must be one of {', '.join(SINKS)}")
    sinks: list[Sink] = []
    if sink in ("auto", "langfuse"):
        if langfuse_configured():
            try:
                sinks.append(LangfuseSink())
            except ImportError:
                logging.getLogger(__name__).warning("Langfuse keys are set but the langfuse package is not installed; "
                                                    "install crossvet[langfuse] to record there")
            except Exception as exc:  # noqa: BLE001  bad settings: say so, keep going
                logging.getLogger(__name__).warning(
                    "Langfuse is configured but could not start (%s); not recording there", type(exc).__name__)
        elif sink == "langfuse":
            raise ValueError("record sink is langfuse but LANGFUSE_PUBLIC_KEY / LANGFUSE_SECRET_KEY are not set")
    if sink == "auto" and otel_configured():
        try:
            sinks.append(OtelSink())
        except ImportError:
            logging.getLogger(__name__).warning("an OTLP endpoint is set but the otel extra is not installed; "
                                                "install crossvet[otel] to send traces there")
    if jsonl and sink in ("auto", "jsonl"):
        sinks.append(JsonlSink(jsonl))
    elif sink == "jsonl":
        raise ValueError("record sink is jsonl but [record] jsonl has no path")
    return Recorder(sinks, content)


def langfuse_installed() -> bool:
    """Whether the Langfuse SDK can be imported (the ``langfuse`` extra)."""
    import importlib.util

    return importlib.util.find_spec("langfuse") is not None
