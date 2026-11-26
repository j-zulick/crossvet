"""The OpenAI-compatible server: the request names the model, commands work, agents keep their tools."""

from __future__ import annotations

import json

import pytest
from starlette.testclient import TestClient

from crossvet import server
from crossvet.providers import AccountError, ProviderError, Reply

Q1 = "Write a Python function that parses '2021 Toyota Tacoma SR5 - 34,210 mi - $31,995'."


@pytest.fixture
def client(cv):
    return TestClient(server.create_app(cv, token=""))


def post(client, messages, model="default", **more):
    return client.post("/v1/chat/completions", json={"model": model, "messages": messages, **more})


def user(text):
    return {"role": "user", "content": text}


def test_health_and_the_model_menu(client):
    assert client.get("/health").json()["status"] == "ok"
    ids = [m["id"] for m in client.get("/v1/models").json()["data"]]
    assert ids[0] == "default" and "anthropic:claude-opus-5-5" in ids and "claude" in ids


def test_the_model_field_picks_the_model(client, fake):
    fake.on("openai:gpt-6.1-sol", "def parse(s): ...")
    data = post(client, [user(Q1)], model="gpt").json()
    assert data["model"] == "openai:gpt-6.1-sol" and data["choices"][0]["message"]["content"] == "def parse(s): ..."
    assert data["crossvet"]["model"] == "openai:gpt-6.1-sol" and data["usage"]["completion_tokens"] == 50
    assert post(client, [user(Q1)]).json()["model"] == "anthropic:claude-sonnet-5-5"


def test_slash_model_switches_the_rest_of_the_conversation(client, fake):
    reply = post(client, [user(Q1), {"role": "assistant", "content": "a"}, user("/model luna")], model="claude").json()
    assert reply["choices"][0]["message"]["content"] == "Crossvet: openai:gpt-6-luna answers the rest of this conversation."
    assert fake.calls == []  # a command calls no model
    history = [user(Q1), {"role": "assistant", "content": "a"}, user("/model luna"),
               {"role": "assistant", "content": reply["choices"][0]["message"]["content"]}, user("Is 48,000 miles high?")]
    assert post(client, history, model="claude").json()["model"] == "openai:gpt-6-luna"
    sent = fake.calls[-1][1]
    assert [m["content"] for m in sent] == [Q1, "a", "Is 48,000 miles high?"]  # the command and its reply are left out


def test_slash_model_alone_shows_the_model_in_use(client):
    text = post(client, [user(Q1), user("/model")], model="gpt").json()["choices"][0]["message"]["content"]
    assert text == "Crossvet: this conversation uses openai:gpt-6.1-sol."


def test_models_cost_and_help_commands(client, fake):
    assert "openai:gpt-6-luna" in post(client, [user("/models")]).json()["choices"][0]["message"]["content"]
    post(client, [user(Q1)], model="luna")
    cost = post(client, [user(Q1), {"role": "assistant", "content": "x"}, user("/cost")]).json()
    text = cost["choices"][0]["message"]["content"]
    assert "This conversation:" in text and "openai:gpt-6-luna" in text and "Today:" in text
    assert "/model NAME" in post(client, [user("/help")]).json()["choices"][0]["message"]["content"]


def test_an_unknown_model_is_a_400_that_lists_the_names(client):
    response = post(client, [user(Q1)], model="gemini")
    assert response.status_code == 400 and "short name" in response.json()["error"]["message"]
    assert post(client, [user("/model gemini")]).status_code == 400


def test_streaming_sends_pieces_then_usage_and_cost(client, fake):
    fake.on("openai:gpt-6-luna", "Low for its age.")
    with client.stream("POST", "/v1/chat/completions", json={"model": "luna", "messages": [user(Q1)], "stream": True}) as r:
        events = [json.loads(line[6:]) for line in r.iter_lines() if line.startswith("data: {")]
    text = "".join(e["choices"][0]["delta"].get("content", "") for e in events)
    assert text == "Low for its age."
    assert events[-1]["choices"][0]["finish_reason"] == "stop" and events[-1]["crossvet"]["model"] == "openai:gpt-6-luna"


def test_a_command_can_be_streamed(client):
    with client.stream("POST", "/v1/chat/completions", json={"messages": [user("/model")], "stream": True}) as r:
        body = r.read().decode()
    assert "anthropic:claude-sonnet-5-5" in body and body.rstrip().endswith("[DONE]")


def test_tools_are_passed_through_and_tool_calls_come_back(client, fake):
    call = {"id": "c1", "type": "function", "function": {"name": "lookup_vin", "arguments": "{\"vin\": \"1\"}"}}
    fake.on("anthropic:claude-opus-5-5", Reply("", "", input_tokens=10, output_tokens=5, tool_calls=[call]))
    tools = [{"type": "function", "function": {"name": "lookup_vin", "parameters": {"type": "object"}}}]
    data = post(client, [user("Decode VIN 1"), user("/model claude"), {"role": "assistant", "content": "ok"}, user("go")],
                tools=tools).json()
    assert data["choices"][0]["message"]["tool_calls"] == [call] and data["choices"][0]["finish_reason"] == "tool_calls"
    model, body, _ = fake.relayed[0]
    assert model == "anthropic:claude-opus-5-5" and body["tools"] == tools
    assert [m["content"] for m in body["messages"]] == ["Decode VIN 1", "go"]


def test_streamed_tool_calls_keep_their_index(client, fake):
    call = {"id": "c1", "type": "function", "function": {"name": "f", "arguments": "{}"}}
    fake.on("openai:gpt-6.1-sol", Reply("", "", tool_calls=[call]))
    with client.stream("POST", "/v1/chat/completions",
                       json={"model": "gpt", "messages": [user("x")], "tools": [{"type": "function"}], "stream": True}) as r:
        events = [json.loads(line[6:]) for line in r.iter_lines() if line.startswith("data: {")]
    calls = [e["choices"][0]["delta"]["tool_calls"][0] for e in events if e["choices"] and "tool_calls" in e["choices"][0]["delta"]]
    assert calls == [{"index": 0, **call}]
    assert [e["choices"][0]["finish_reason"] for e in events if e["choices"]][-1] == "tool_calls"
    assert events[-1]["choices"] == [] and events[-1]["crossvet"]["model"] == "openai:gpt-6.1-sol"


def test_dropped_fields_are_reported(client, fake):
    fake.on("openai:gpt-6.1-sol", Reply("ok", "", dropped=["logprobs", "seed"]))
    data = post(client, [user("x")], model="gpt", tools=[{"type": "function"}], seed=1, logprobs=True).json()
    assert data["crossvet"]["dropped"] == ["logprobs", "seed"]


@pytest.mark.parametrize(("error", "status", "kind"), [
    (ProviderError("HTTP 500 from api.openai.com"), 502, "upstream_error"),
    (AccountError("HTTP 401 from api.openai.com"), 402, "account_refused"),
])
def test_failures_name_the_model_and_say_what_to_do(client, fake, error, status, kind):
    fake.on("openai:gpt-6.1-sol", error)
    response = post(client, [user(Q1)], model="gpt")
    assert response.status_code == status and response.json()["error"]["type"] == kind
    if status == 502:
        assert response.json()["error"]["message"].startswith("gpt: ") and "/model NAME" in response.json()["error"]["message"]


def test_a_spend_cap_is_a_429(make):
    client = TestClient(server.create_app(make(limits={"max_usd_per_call": 0.001}), token=""))
    response = post(client, [user(Q1)], model="claude")
    assert response.status_code == 429 and response.json()["error"]["type"] == "budget_exceeded"


def test_bad_and_oversized_requests(make, client):
    assert client.post("/v1/chat/completions", content=b"{").status_code == 400
    assert post(client, [{"role": "system", "content": "x"}]).status_code == 400
    small = TestClient(server.create_app(make(limits={"max_request_bytes": 100}), token=""))
    assert post(small, [user("x" * 200)]).status_code == 413


def test_a_token_is_required_when_set(cv):
    client = TestClient(server.create_app(cv, token="t" * 20))
    assert client.get("/v1/models").status_code == 401
    assert post(client, [user(Q1)]).status_code == 401
    assert client.get("/v1/models", headers={"Authorization": "Bearer " + "t" * 20}).status_code == 200
    assert client.get("/health").status_code == 200


def test_a_conversation_keeps_one_thread_id(client, fake):
    first = post(client, [user(Q1)], model="luna").json()["crossvet"]["thread"]
    again = post(client, [user(Q1), {"role": "assistant", "content": "x"}, user("more")], model="luna").json()
    assert again["crossvet"]["thread"] == first
    header = client.post("/v1/chat/completions", json={"model": "luna", "messages": [user(Q1)]},
                         headers={"x-crossvet-thread": "mine"}).json()
    assert header["crossvet"]["thread"] == "mine"


def test_serving_beyond_this_computer_needs_a_long_token(monkeypatch, capsys):
    monkeypatch.setenv("CROSSVET_TOKEN", "short")
    assert server.serve("0.0.0.0", 8787) == 2
    assert "at least 16 characters" in capsys.readouterr().err


def test_auto_from_the_model_menu_answers_and_explains(make, fake, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "x")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "x")
    cv = make(slots={"strong": ["openai:gpt-6.1-sol"], "quick": ["openai:gpt-6-luna"]})
    client = TestClient(server.create_app(cv, token=""))
    assert "auto" in [m["id"] for m in client.get("/v1/models").json()["data"]]
    fake.on("openai:gpt-6.1-sol", "def parse(s): ...")
    data = post(client, [user(Q1)], model="auto").json()
    assert data["model"] == "openai:gpt-6.1-sol" and data["crossvet"]["decision"]["slot"] == "strong"
    history = [user(Q1), {"role": "assistant", "content": "def parse(s): ..."}]
    why = post(client, [*history, user("/why")]).json()["choices"][0]["message"]["content"]
    assert "openai:gpt-6.1-sol answered (kind: code, slot: strong)" in why
    rated = post(client, [*history, user("/bad wrong regex")]).json()["choices"][0]["message"]["content"]
    assert "rated the last answer (openai:gpt-6.1-sol" in rated
    assert cv.lab.ratings()[-1]["note"] == "wrong regex"
    stream = client.post("/v1/chat/completions", json={"model": "auto", "stream": True, "messages": [user(Q1)]})
    assert '"model": "auto"' in stream.text and "decision" in stream.text


def test_retry_stronger_moves_up_a_slot(make, fake, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "x")
    cv = make(slots={"quick": ["openai:gpt-6-luna"], "balanced": ["openai:gpt-6.1-terra"], "strong": ["openai:gpt-6.1-sol"]})
    client = TestClient(server.create_app(cv, token=""))
    fake.on("openai:gpt-6-luna", "Low.")
    question = user("Is 48,000 miles high for a 2019 CR-V?")
    post(client, [question], model="auto")
    fake.on("openai:gpt-6.1-terra", "It is low for a five-year-old SUV.")
    text = post(client, [question, {"role": "assistant", "content": "Low."}, user("/retry stronger")], model="auto").json()
    assert text["choices"][0]["message"]["content"].startswith("It is low") and "openai:gpt-6.1-terra" in text["choices"][0]["message"]["content"]
    assert fake.calls[-1][1] == [question]


def test_a_private_request_with_nowhere_private_is_a_400(make, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "x")
    client = TestClient(server.create_app(make(slots={"balanced": ["openai:gpt-6.1-terra"]}), token=""))
    reply = post(client, [user("Confidential: my card is 4111 1111 1111 1111, pay the deposit")], model="auto")
    assert reply.status_code == 400 and reply.json()["error"]["type"] == "private_request"
