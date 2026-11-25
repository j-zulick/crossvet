"""Every turn and rating is kept locally and copied to Langfuse or a JSON-lines file."""

from __future__ import annotations

import json
from contextlib import contextmanager

import pytest

from crossvet.chat import cli
from crossvet.chat.config import parse
from crossvet.chat.hub import Hub
from crossvet.chat.memory import Memory
from crossvet.chat.providers import ProviderError
from crossvet.chat.record import (
    JsonlSink,
    LangfuseSink,
    Recorder,
    build,
    trace_id_for,
)

from .conftest import CONFIG


class FakeLangfuse:
    """Records what the sink sends, in the Langfuse SDK's call shapes."""

    def __init__(self) -> None:
        self.generations: list[dict] = []
        self.scores: list[dict] = []
        self.scopes: list[dict] = []
        self.flushed = 0

    def start_observation(self, **kw):
        self.generations.append(kw)
        return self

    def end(self):
        self.generations[-1]["ended"] = True

    def create_score(self, **kw):
        self.scores.append(kw)

    def flush(self):
        self.flushed += 1

    def propagate(self, **kw):
        self.scopes.append(kw)

        @contextmanager
        def scope():
            yield

        return scope()


@pytest.fixture
def langfuse() -> FakeLangfuse:
    return FakeLangfuse()


@pytest.fixture
def rec_hub(models, langfuse, tmp_path) -> Hub:
    sinks = [LangfuseSink(langfuse, langfuse.propagate), JsonlSink(str(tmp_path / "turns.jsonl"))]
    return Hub(config=parse(CONFIG, "t"), memory=Memory(":memory:"), caller=models, recorder=Recorder(sinks))


def test_each_answer_becomes_one_generation_with_the_routing_reason(rec_hub, langfuse, tmp_path):
    answer = rec_hub.ask("Fix this Python bug", thread="th", author="cli")
    gen = langfuse.generations[0]
    assert gen["trace_context"]["trace_id"] == trace_id_for(rec_hub.memory.id, answer.turn_id) and gen["ended"]
    assert gen["as_type"] == "generation" and gen["model"] == "anthropic:big" and gen["input"] == "Fix this Python bug"
    assert gen["metadata"]["kind"] == "code" and gen["metadata"]["slot"] == "strong" and "code task" in gen["metadata"]["why"]
    assert gen["usage_details"] == {"input": 100, "output": 50} and gen["cost_details"] == {"total": answer.cost}
    assert langfuse.scopes[0]["session_id"] == "th" and "kind:code" in langfuse.scopes[0]["tags"]
    assert langfuse.scores[0]["name"] == "escalated" and langfuse.scores[0]["value"] == 0.0
    rows = [json.loads(line) for line in (tmp_path / "turns.jsonl").read_text().splitlines()]
    assert rows[0]["type"] == "turn" and rows[0]["turn_id"] == answer.turn_id and rows[0]["answer"] == answer.text


def test_escalation_is_scored(rec_hub, models, langfuse):
    models.set("anthropic:big", ProviderError("HTTP 500"))
    rec_hub.ask("Fix this Python bug")
    assert langfuse.scores[-1] == {"trace_id": langfuse.generations[-1]["trace_context"]["trace_id"], "name": "escalated",
                                   "value": 1.0, "data_type": "BOOLEAN", "comment": None}
    assert "escalated" in langfuse.scopes[-1]["tags"]


def test_metadata_only_leaves_the_text_out_of_the_sinks_but_not_the_store(models, langfuse):
    hub = Hub(config=parse(CONFIG, "t"), memory=Memory(":memory:"), caller=models,
              recorder=Recorder([LangfuseSink(langfuse, langfuse.propagate)], content="metadata"))
    answer = hub.ask("What is the capital of France?")
    assert langfuse.generations[0]["input"] is None and langfuse.generations[0]["output"] is None
    assert hub.memory.turns(answer.thread)[0].content == "What is the capital of France?"
    hub.feedback(False, turn_id=answer.turn_id, comment="private detail")
    assert langfuse.scores[-1]["comment"] is None and hub.memory.ratings(answer.turn_id)[-1].comment == "private detail"


def test_feedback_retry_and_switch_become_scores(rec_hub, langfuse):
    first = rec_hub.ask("What is the capital of France?", thread="f")
    rec_hub.feedback(True, thread="f", comment="right")
    again = rec_hub.retry("f", stronger=True)
    rec_hub.ask("And of Spain?", thread="f", model="openai:big")
    names = [(r.turn_id, r.name, r.value) for r in rec_hub.memory.ratings()]
    assert (first.turn_id, "user-feedback", 1.0) in names and (first.turn_id, "retried", 1.0) in names
    assert (again.turn_id, "switched", 1.0) in names
    sent = {(s["name"], s["value"]) for s in langfuse.scores}
    assert {("user-feedback", 1.0), ("retried", 1.0), ("switched", 1.0)} <= sent
    trace = trace_id_for(rec_hub.memory.id, first.turn_id)
    assert all(s["trace_id"] == trace for s in langfuse.scores if s["name"] in ("user-feedback", "retried"))


def test_ratings_are_append_only_and_need_a_real_answer(hub):
    answer = hub.ask("What is the capital of France?")
    hub.feedback(True, turn_id=answer.turn_id)
    with pytest.raises(Exception, match="append-only"):
        hub.memory.db.execute("UPDATE feedback SET value=0")
    with pytest.raises(ValueError, match="no saved answer"):
        hub.feedback(True, turn_id=answer.turn_id - 1)  # the user's message, not an answer
    with pytest.raises(ValueError, match="no answer to rate"):
        Hub(config=hub.config, memory=Memory(":memory:"), caller=lambda *a: None).feedback(True)


def test_trace_ids_are_stable_per_store(tmp_path):
    first = Memory(str(tmp_path / "a.db"))
    assert Memory(str(tmp_path / "a.db")).id == first.id != Memory(str(tmp_path / "b.db")).id
    tid = trace_id_for(first.id, 7)
    assert len(tid) == 32 and int(tid, 16) and tid == trace_id_for(first.id, 7) != trace_id_for(first.id, 8)


def test_a_failing_sink_never_breaks_a_turn(models):
    class Broken:
        def turn(self, record):
            raise RuntimeError("down")

        score = flush = turn

    recorder = Recorder([Broken()])
    hub = Hub(config=parse(CONFIG, "t"), memory=Memory(":memory:"), caller=models, recorder=recorder)
    assert hub.ask("hello there").text and recorder.errors and "down" in recorder.errors[0]


def test_build_picks_sinks_from_settings_and_keys(monkeypatch, tmp_path):
    monkeypatch.delenv("LANGFUSE_PUBLIC_KEY", raising=False)
    monkeypatch.delenv("LANGFUSE_SECRET_KEY", raising=False)
    assert build("auto").sinks == [] and build("off", jsonl=str(tmp_path / "x")).sinks == []
    assert isinstance(build("auto", jsonl=str(tmp_path / "x.jsonl")).sinks[0], JsonlSink)
    with pytest.raises(ValueError, match="LANGFUSE_PUBLIC_KEY"):
        build("langfuse")
    with pytest.raises(ValueError, match="no path"):
        build("jsonl")
    with pytest.raises(ValueError):
        parse({"record": {"sink": "datadog"}})
    cfg = parse({"record": {"sink": "jsonl", "content": "metadata", "jsonl": "~/t.jsonl"}})
    assert (cfg.record_sink, cfg.record_content, cfg.record_jsonl) == ("jsonl", "metadata", "~/t.jsonl")


def test_server_feedback_endpoint_and_commands(rec_hub, langfuse):
    from starlette.testclient import TestClient

    from crossvet.chat.server import create_app

    client = TestClient(create_app(rec_hub, token=""))
    convo = [{"role": "user", "content": "What is the capital of France?"}]
    data = client.post("/v1/chat/completions", json={"model": "auto", "messages": convo}).json()
    turn = data["crossvet"]["turn"]
    assert client.post("/api/feedback", json={"turn": turn, "value": "bad", "comment": "wrong"}).json()["good"] is False
    good = client.post("/v1/chat/completions", json={"model": "auto", "messages": convo + [
        {"role": "assistant", "content": "Paris"}, {"role": "user", "content": "/good"}]}).json()
    assert "rated good" in good["choices"][0]["message"]["content"]
    assert [r.value for r in rec_hub.memory.ratings(turn)] == [0.0, 1.0]
    assert client.post("/api/feedback", json={"value": "good"}).status_code == 400


def test_cli_rates_and_log_shows_ratings(hub, models, monkeypatch, capsys):
    monkeypatch.setattr(cli, "_hub", lambda: hub)
    lines = iter(["What is the capital of France?", "/good spot on", "/quit"])
    monkeypatch.setattr("builtins.input", lambda _: next(lines))
    assert cli.main([]) == 0
    assert cli.main(["feedback", "bad", "--comment", "changed my mind"]) == 0
    thread = hub.memory.recent(1)[0].thread
    assert cli.main(["log", "--thread", thread]) == 0
    out = capsys.readouterr().out
    assert "user-feedback=1 · user-feedback=0" in out and "#2" in out


def test_mcp_rate_answer(hub):
    from crossvet.chat.mcp_server import tools

    t = tools(hub, app="claude")
    answer = t["ask"]("What is the capital of France?")
    assert t["rate_answer"](good=True, turn=answer["turn"])["good"] is True
    assert hub.memory.ratings(answer["turn"])[0].source == "claude"
