"""Routing by input type, per-kind tables, goals, cascade, privacy, trimming, the learned router and its report (offline)."""

from __future__ import annotations

import pytest

from crossvet.chat import learned
from crossvet.chat.config import parse
from crossvet.chat.hub import Hub, NoModel
from crossvet.chat.inputs import detect, looks_private, to_anthropic
from crossvet.chat.memory import Memory
from crossvet.chat.providers import Reply, anthropic_turns
from crossvet.chat.record import Recorder
from crossvet.chat.routing import route

from .conftest import CONFIG, FakeModels

IMAGE = {"type": "image_url", "image_url": {"url": "data:image/png;base64,iVBORw0KGgo="}}
PDF = {"type": "file", "file": {"filename": "deck.pdf", "file_data": "data:application/pdf;base64,JVBERi0="}}
AUDIO = {"type": "input_audio", "input_audio": {"data": "UklGRg==", "format": "wav"}}


def make(extra: dict | None = None, models: FakeModels | None = None, **kw) -> tuple[Hub, FakeModels]:
    data = {**CONFIG, **(extra or {})}
    data["slots"] = {**CONFIG["slots"], **(extra or {}).get("slots", {})}
    data["models"] = {**CONFIG["models"], **(extra or {}).get("models", {})}
    models = models or FakeModels()
    return Hub(config=parse(data, "test"), memory=Memory(":memory:"), caller=models, recorder=Recorder(), **kw), models


VISION = {"slots": {"vision": ["openai:eyes", "anthropic:eyes"]},
          "models": {"openai:eyes": {"takes": ["image", "pdf"]}, "anthropic:big": {"takes": []}}}


# --- input type ---


def test_an_image_goes_to_the_vision_slot_and_reaches_the_model_as_a_part():
    hub, models = make(VISION)
    answer = hub.ask("What does this chart show?", parts=[{"type": "text", "text": "What does this chart show?"}, IMAGE])
    assert answer.decision.slot == "vision" and answer.model == "openai:eyes"
    assert "includes an image" in answer.decision.explain()
    assert models.calls[0][1][-1]["content"][1] == IMAGE
    saved = hub.memory.turns(answer.thread)[0].content
    assert saved.endswith("[with image]") and "base64" not in saved


def test_models_that_say_they_dont_take_an_input_are_skipped():
    config = parse({**CONFIG, "models": {**CONFIG["models"], "openai:mid": {"takes": ["pdf"]}, "google:wide": {"takes": ["image"]}}},
                   "test")
    decision = route("Summarize this", config, inputs=detect([PDF], "Summarize this"))
    assert decision.slot == "long" and "No model in the slot says it takes pdf; trying them anyway" in decision.explain()
    assert decision.candidates == ["google:wide"]  # skipping every model would leave none


def test_a_pdf_goes_to_the_long_slot_and_audio_is_transcribed_when_set():
    hub, models = make()
    assert hub.decide("Summarize this", inputs=detect([PDF], "Summarize this")).slot == "long"
    heard = []
    hub, models = make({"inputs": {"transcribe": "openai:whisper"}}, transcriber=lambda m, part: heard.append(m) or "fix the login bug")
    answer = hub.ask("", parts=[AUDIO])
    assert heard == ["openai:whisper"] and "[transcribed audio]" in models.calls[0][1][-1]["content"]
    assert answer.decision.inputs == []


def test_audio_without_a_transcriber_goes_to_the_audio_slot():
    hub, _ = make({"slots": {"audio": ["openai:ears"]}})
    assert hub.decide("listen", inputs=detect([AUDIO], "listen")).candidates == ["openai:ears"]


def test_pasted_code_makes_a_vague_request_a_code_task():
    decision = route("thoughts?\n```python\ndef f(x):\n    return x\n```", parse(CONFIG, "test"),
                     inputs=detect(None, "thoughts?\n```python\ndef f(x):\n    return x\n```"))
    assert decision.task.kind == "code" and decision.slot == "strong"


def test_anthropic_gets_its_own_shapes_and_refuses_audio():
    blocks = to_anthropic([{"type": "text", "text": "hi"}, IMAGE, PDF])
    assert blocks[1] == {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": "iVBORw0KGgo="}}
    assert blocks[2]["type"] == "document" and blocks[2]["source"]["media_type"] == "application/pdf"
    system, turns = anthropic_turns([{"role": "system", "content": "be brief"}, {"role": "user", "content": [IMAGE]}])
    assert system == "be brief" and turns[0]["content"][0]["type"] == "image"
    with pytest.raises(Exception, match="audio"):
        anthropic_turns([{"role": "user", "content": [AUDIO]}])


# --- per-kind table and goals ---


def test_kinds_table_puts_named_models_first():
    config = parse({**CONFIG, "kinds": {"code": ["openai:big"]}}, "test")
    decision = route("Fix this Python function that throws KeyError", config)
    assert decision.candidates[0] == "openai:big" and "[kinds]" in decision.explain()
    with pytest.raises(ValueError, match="unknown kind"):
        parse({**CONFIG, "kinds": {"poetry": ["openai:big"]}}, "test")


def test_goals_best_and_cheapest():
    config = parse(CONFIG, "test")
    assert route("Write a short thank-you note", config, goal="best").slot == "strong"
    cheap = route("Fix this Python function that throws KeyError", config, goal="cheapest")
    assert cheap.candidates[:3] == ["openai:small", "anthropic:small", "openai:mid"]
    assert cheap.candidates[-1] == "anthropic:big" and "cheapest answer that passes" in cheap.explain()


def test_fastest_orders_by_measured_speed():
    hub, models = make()
    for model, seconds in (("anthropic:big", 9.0), ("openai:big", 2.0)):
        for _ in range(3):
            models.set(model, Reply(text="ok", model=model, input_tokens=10, output_tokens=10, seconds=seconds))
            hub.ask("Fix this Python function that throws KeyError", model=model)
    decision = hub.decide("Fix this Python function that throws KeyError", goal="fastest")
    assert decision.candidates[:2] == ["openai:big", "anthropic:big"] and "median 2.0 s" in decision.explain()
    assert hub.speeds()["anthropic:big"] == 9.0


def test_cascade_climbs_only_when_a_check_fails():
    hub, models = make({"router": {"cascade": True}})
    models.set("openai:small", Reply(text="cut off", model="openai:small", truncated=True))
    models.set("anthropic:small", Reply(text="cut off", model="anthropic:small", truncated=True))
    answer = hub.ask("Fix this Python function that throws KeyError")
    assert [a.model for a in answer.attempts] == ["openai:small", "anthropic:small", "openai:mid"]
    assert answer.model == "openai:mid" and "cascade is on" in answer.decision.explain()


# --- privacy and history ---


def test_private_requests_stay_local_and_their_text_stays_out_of_the_sinks():
    sent = []

    class Sink:
        def turn(self, record):
            sent.append(record)

    hub, models = make({"slots": {"quick": ["ollama:gemma3", "openai:small"]}})
    hub.recorder = Sink()
    answer = hub.ask("Summarize: this memo is confidential, Q3 numbers attached")
    assert answer.model == "ollama:gemma3" and answer.decision.candidates == ["ollama:gemma3"]
    assert 'the word "confidential"' in answer.decision.explain()
    assert sent[0].prompt is None and sent[0].answer is None and models.calls[0][0] == "ollama:gemma3"
    assert hub.ask("Summarize: quarterly memo", private=True).model == "ollama:gemma3"
    assert "openai:small" in hub.ask("Summarize: this memo is confidential", private=False).decision.candidates
    with pytest.raises(NoModel, match="not a local model"):
        hub.ask("my key is sk-abcdefghijklmnopqrstuvwx", model="openai:big")


def test_a_private_request_with_no_local_model_is_refused_not_sent():
    hub, models = make()
    with pytest.raises(NoModel, match="no local model"):
        hub.ask("SSN 123-45-6789, fill in the form")
    assert models.calls == []
    assert looks_private("call 412-555-1234 about order 1234567890") == ""


def test_quick_models_get_a_short_history():
    hub, models = make({"memory": {"quick_history_turns": 2}})
    for n in range(6):
        hub.ask(f"Translate to French: line {n}", thread="t")
    hub.ask("Translate to French: last line", thread="t")
    sent = models.calls[-1][1]
    assert len(sent) == 1 + 4 + 1  # system, the last two turns (question and answer each), the request
    assert "only the last 2 turn(s)" in hub.memory.turns("t")[-1].meta["why"]


# --- learned router and report ---


def rated(hub: Hub, prompt: str, slot: str, good: bool) -> None:
    answer = hub.ask(prompt, slot=slot)
    hub.feedback(good, turn_id=answer.turn_id)


def test_the_learned_router_trains_on_ratings_and_is_compared_with_the_rules():
    hub, _ = make({"router": {"use": "learned", "learned_min_confidence": 0.5}})
    with pytest.raises(ValueError, match="at least 30"):
        learned.train(hub.memory, hub.config)
    for n in range(20):
        rated(hub, f"Write a short thank-you note to my landlord number {n}", "quick", False)   # quick was not enough
        rated(hub, f"Summarize the attached meeting notes number {n}", "quick", True)
    model = learned.train(hub.memory, hub.config)
    assert model.examples == 40 and model.held_out == 8 and model.accuracy is not None
    assert model.predict("Write a short thank-you note to my neighbour")[0] == "balanced"
    decision = hub.decide("Summarize the attached meeting notes from Tuesday")
    assert decision.router == "learned" and decision.slot == "quick"
    report = __import__("crossvet.chat.report", fromlist=["weekly"]).weekly(hub)
    assert "## Routing" in report and "Learned router" in report and "Against always using anthropic:big" in report


def test_bench_writes_a_kinds_table():
    from crossvet.chat import bench

    rows = [{"model": "openai:mid", "case": "a", "kind": "code", "score": 1.0, "cost": 0.01, "error": ""},
            {"model": "anthropic:big", "case": "a", "kind": "code", "score": 0.95, "cost": 0.002, "error": ""},
            {"model": "openai:small", "case": "a", "kind": "code", "score": 0.2, "cost": 0.0001, "error": ""},
            {"model": "google:wide", "case": "l", "kind": "long", "score": 1.0, "cost": 0.1, "error": ""}]
    assert bench.best_per_kind(rows) == {"code": ["anthropic:big", "openai:mid", "openai:small"]}  # "long" is not a chat kind


def test_server_passes_images_goal_and_privacy(hub, models):
    from starlette.testclient import TestClient

    from crossvet.chat.server import create_app

    client = TestClient(create_app(hub, token=""))
    body = {"model": "crossvet/cheapest", "messages": [{"role": "user", "content": [{"type": "text", "text": "Fix this Python bug"}]}]}
    reply = client.post("/v1/chat/completions", json=body).json()
    assert reply["model"] == "openai:small"
    names = [m["id"] for m in client.get("/v1/models").json()["data"]]
    assert {"crossvet/best", "crossvet/cheapest", "crossvet/fastest"} <= set(names)
    body = {"model": "auto", "messages": [{"role": "user", "content": [{"type": "text", "text": "Describe it"}, IMAGE]}]}
    client.post("/v1/chat/completions", json=body)
    assert models.calls[-1][1][-1]["content"][1] == IMAGE
    refused = client.post("/v1/chat/completions", headers={"x-crossvet-private": "1"},
                          json={"model": "auto", "messages": [{"role": "user", "content": "hello"}]})
    assert refused.status_code >= 400 and "local model" in refused.text


# --- v0.8.0: local first, prompt caching, OpenTelemetry ---


def test_local_first_tries_local_models_on_quick_requests():
    hub, models = make({"slots": {"quick": ["openai:small"], "balanced": ["ollama:gemma3", "openai:mid"]},
                        "router": {"local_first": True}})
    decision = hub.decide("Translate to French: good morning")
    assert decision.candidates[:2] == ["ollama:gemma3", "openai:small"] and "Local first" in decision.explain()
    assert hub.decide("Write a short thank-you note").candidates[0] == "openai:mid"  # balanced: unchanged


def test_long_system_text_is_marked_for_anthropic_caching_and_cached_tokens_are_counted(monkeypatch):
    import httpx

    from crossvet.chat import providers

    sent = []

    def handler(request):
        sent.append(__import__("json").loads(request.content))
        return httpx.Response(200, json={"content": [{"type": "text", "text": "ok"}], "stop_reason": "end_turn",
                                         "usage": {"input_tokens": 10, "cache_read_input_tokens": 3000, "output_tokens": 5}})

    monkeypatch.setenv("ANTHROPIC_API_KEY", "k")
    reply = providers.call("anthropic:big", [{"role": "system", "content": "x" * 5000}, {"role": "user", "content": "hi"}],
                           100, httpx.MockTransport(handler))
    assert sent[0]["system"][0]["cache_control"] == {"type": "ephemeral"}
    assert reply.input_tokens == 3010 and reply.extra["cached_tokens"] == 3000
    providers.call("anthropic:big", [{"role": "system", "content": "short"}, {"role": "user", "content": "hi"}],
                   100, httpx.MockTransport(handler))
    assert sent[1]["system"] == "short"
    assert providers.cached_tokens({"prompt_tokens_details": {"cached_tokens": 42}}) == 42


def test_cached_tokens_reach_the_report():
    hub, models = make()
    models.set("openai:small", Reply(text="ok", model="openai:small", input_tokens=1000, output_tokens=10,
                                     extra={"cached_tokens": 800}))
    hub.ask("Translate to French: hello")
    report = __import__("crossvet.chat.report", fromlist=["weekly"]).weekly(hub)
    assert "800 of 1,000 input tokens (80%)" in report


def test_turns_become_otel_spans_without_text():
    pytest.importorskip("opentelemetry.sdk", reason="needs the otel extra")
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import SimpleSpanProcessor
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import (
        InMemorySpanExporter,
    )

    from crossvet.chat.record import OtelSink

    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    hub, _ = make()
    hub.recorder = Recorder([OtelSink(provider.get_tracer("test"))])
    answer = hub.ask("Translate to French: secret plans")
    hub.feedback(True, turn_id=answer.turn_id)
    spans = exporter.get_finished_spans()
    turn = spans[0].attributes
    assert turn["gen_ai.request.model"] == "openai:small" and turn["gen_ai.system"] == "openai" and turn["crossvet.kind"] == "translate"
    assert "secret" not in str(dict(turn)) and spans[1].events[0].name == "user-feedback"
