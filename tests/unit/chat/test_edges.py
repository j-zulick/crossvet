"""Providers, setup, the benchmark, the HTTP server, the MCP tools and the command line. All offline."""

import json

import httpx
import pytest

from crossvet.chat import bench, cli, providers, setup
from crossvet.chat.hub import Hub
from crossvet.chat.mcp_server import tools
from crossvet.chat.memory import Memory
from crossvet.chat.providers import ProviderError, Reply

from .conftest import CONFIG, parse

# --- providers ---


def transport(handler):
    return httpx.MockTransport(handler)


def test_openai_style_call_and_openrouter_cost(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "k-test")
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"], seen["auth"], seen["body"] = str(request.url), request.headers["authorization"], json.loads(request.content)
        return httpx.Response(200, json={"choices": [{"message": {"content": "hi"}, "finish_reason": "stop"}],
                                         "usage": {"prompt_tokens": 7, "completion_tokens": 3, "cost": 0.0012}})

    reply = providers.call("openrouter:x-ai/grok", [{"role": "user", "content": "hello"}], 50, transport(handler))
    assert (reply.text, reply.cost, reply.input_tokens, reply.model) == ("hi", 0.0012, 7, "openrouter:x-ai/grok")
    assert seen["url"] == "https://openrouter.ai/api/v1/chat/completions" and seen["auth"] == "Bearer k-test"
    assert seen["body"] == {"model": "x-ai/grok", "messages": [{"role": "user", "content": "hello"}], "max_tokens": 50,
                            "usage": {"include": True}}


def test_anthropic_call_moves_system_out_and_detects_truncation(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "k-test")
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["body"], seen["key"] = json.loads(request.content), request.headers["x-api-key"]
        return httpx.Response(200, json={"content": [{"type": "thinking", "thinking": "..."}, {"type": "text", "text": "partial"}],
                                         "stop_reason": "max_tokens", "usage": {"input_tokens": 9, "output_tokens": 4}})

    reply = providers.call("anthropic:claude-x", [{"role": "system", "content": "be brief"}, {"role": "user", "content": "q"}],
                           transport=transport(handler))
    assert reply.text == "partial" and reply.truncated and reply.cost is None
    assert seen["body"]["system"] == "be brief" and seen["body"]["messages"] == [{"role": "user", "content": "q"}]


def test_provider_errors_are_clear_and_never_show_the_key(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with pytest.raises(ProviderError, match="OPENAI_API_KEY is not set"):
        providers.call("openai:gpt", [{"role": "user", "content": "q"}])
    monkeypatch.setenv("OPENAI_API_KEY", "test-key-not-real")
    with pytest.raises(ProviderError) as info:
        providers.call("openai:gpt", [{"role": "user", "content": "q"}], transport=transport(lambda r: httpx.Response(401, text="bad key")))
    assert "HTTP 401" in str(info.value) and "test-key-not-real" not in str(info.value)
    with pytest.raises(ProviderError, match="reply shape"):
        providers.call("openai:gpt", [{"role": "user", "content": "q"}], transport=transport(lambda r: httpx.Response(200, json={})))
    with pytest.raises(ProviderError, match="provider:model"):
        providers.split("gpt-4")


def test_vendor_of_and_available(monkeypatch):
    assert providers.vendor_of("openrouter:anthropic/claude") == "anthropic"
    assert providers.vendor_of("xai:grok") == providers.vendor_of("openrouter:x-ai/grok") == "x-ai"
    monkeypatch.delenv("LOCAL_BASE_URL", raising=False)
    assert providers.available("ollama") and not providers.available("local")


def test_local_server_needs_no_key(monkeypatch):
    monkeypatch.setenv("LOCAL_BASE_URL", "http://127.0.0.1:9999/v1")
    monkeypatch.delenv("LOCAL_API_KEY", raising=False)

    def handler(request: httpx.Request) -> httpx.Response:
        assert "authorization" not in request.headers and str(request.url) == "http://127.0.0.1:9999/v1/chat/completions"
        return httpx.Response(200, json={"choices": [{"message": {"content": [{"type": "text", "text": "ok"}]}}]})

    assert providers.call("local:gemma", [{"role": "user", "content": "q"}], transport=transport(handler)).text == "ok"


# --- setup ---

NOW = 1_800_000_000


def entry(model_id, cost_in, cost_out, context=200_000, age_days=30, outputs=("text",), tools=True):
    return {"id": model_id, "context_length": context, "created": NOW - age_days * 86400,
            "pricing": {"prompt": str(cost_in / 1e6), "completion": str(cost_out / 1e6)},
            "architecture": {"output_modalities": list(outputs)}, "supported_parameters": ["tools"] if tools else []}


CATALOG = [
    # OpenAI: six recent general models; the middle third's newest is mid-new, the top third's newest is top-new
    entry("openai/small", 0.1, 0.5, age_days=60), entry("openai/small-old", 0.2, 1, age_days=150),
    entry("openai/mid-old", 1, 5, age_days=120), entry("openai/mid-new", 2, 10, age_days=5, context=400_000),
    entry("openai/top-old", 10, 50, age_days=80), entry("openai/top-new", 8, 40, age_days=6),
    # Anthropic: only two recent models, so the 400-day window is used
    entry("anthropic/small", 0.1, 0.6, age_days=40), entry("anthropic/big", 4, 20, age_days=50), entry("anthropic/older", 5, 25, age_days=300),
    entry("x-ai/grok-a", 2, 6, age_days=130), entry("x-ai/grok-b", 2, 6, age_days=100), entry("x-ai/grok-c", 2, 6, age_days=60),
    entry("google/wide", 0.5, 2, context=2_000_000),
    # left out: too old, not text-only, a variant tag, another vendor, special-purpose names, no tool calling, no price
    entry("openai/ancient", 0.01, 0.01, age_days=900), entry("openai/picture", 1, 1, outputs=("image", "text")),
    entry("openai/small:free", 0.1, 0.5), entry("meta/llama", 0.1, 0.1), entry("openai/gpt-oss-safeguard", 0.05, 0.2),
    entry("openai/gpt-audio", 2, 10), entry("openai/top-pro", 30, 180), entry("google/gemma-small", 0.05, 0.2),
    entry("google/flash-preview", 0.3, 1), entry("openai/no-tools", 0.01, 0.02, tools=False), {"id": "openai/broken"},
]


def test_slots_from_the_openrouter_list():
    slots, models = setup.from_catalog(CATALOG, now=NOW)
    assert slots["quick"] == ["openrouter:openai/small", "openrouter:anthropic/small", "openrouter:google/wide", "openrouter:x-ai/grok-a"]
    assert slots["balanced"][:2] == ["openrouter:openai/mid-new", "openrouter:anthropic/big"]
    assert slots["strong"] == ["openrouter:openai/top-new", "openrouter:anthropic/older", "openrouter:google/wide", "openrouter:x-ai/grok-c"]
    assert slots["fresh"] == ["openrouter:x-ai/grok-c"]                 # the newest xAI model
    assert slots["long"][0] == "openrouter:google/wide"
    assert slots["reviewer"][0] == "openrouter:anthropic/older"         # a different vendor than the first strong model
    assert models["openrouter:openai/mid-new"] == {"context": 400_000, "input": 2.0, "output": 10.0}
    left_out = ("ancient", "picture", "free", "meta", "safeguard", "audio", "top-pro", "gemma", "preview", "no-tools", "broken")
    assert not any(word in m for m in models for word in left_out)


def test_init_text_parses_back_and_notes_gaps(monkeypatch, tmp_path):
    import tomllib

    for key in ("OPENAI_API_KEY", "ANTHROPIC_API_KEY", "OPENROUTER_API_KEY"):
        monkeypatch.delenv(key, raising=False)
    text, notes = setup.build(False)
    assert parse(tomllib.loads(text)).all_models() == [] and any("slots are empty" in n for n in notes)
    monkeypatch.setenv("OPENAI_API_KEY", "k")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "k")
    text, notes = setup.build(False)
    cfg = parse(tomllib.loads(text))
    assert cfg.slots["quick"] == ["openai:gpt-6-luna", "anthropic:claude-haiku-5-5"] and cfg.slots["reviewer"]
    assert cfg.max_usd_per_day == 5.0 and cfg.info("openai:gpt-6-luna").input == 0.10
    assert "API keys are NOT stored here" in text and "k" not in [line.split("=")[-1].strip() for line in text.splitlines()]
    text, notes = setup.build(True, transport=httpx.MockTransport(lambda r: httpx.Response(200, json={"data": CATALOG})))
    assert "openrouter:" in text and any("OPENROUTER_API_KEY is not set" in n for n in notes)


# --- benchmark ---


def test_scorers():
    by_name = {c.name: c for c in bench.CASES}
    assert by_name["zip"].score("34236") == 1.0 and by_name["zip"].score("34231") == 0.0
    assert by_name["missing-search"].score("It was missing from 2.") == 1.0 and by_name["missing-search"].score("1") == 0.0
    assert by_name["out-the-door"].score("The total is $15,802.65") == 1.0 and by_name["out-the-door"].score("15687") == 0.0
    listing = '```json\n{"year": 2019, "make": "Ford", "model": "EcoSport", "trim": "Titanium", "miles": 115176, "price": 6799}\n```'
    assert by_name["listing"].score(listing) == 1.0 and by_name["listing"].score("2019 Ford EcoSport, 6799") == 0.0
    assert by_name["search-summary"].score("Kelley Blue Book led; Sarasota Ford was the only dealer site.") == 1.0
    assert by_name["search-summary"].score("Kelley Blue Book Sarasota Ford " + "word " * 60) == 0.5
    good = "```python\ndef parse_miles(text):\n    t = text.lower().split()[0].replace(',', '')\n    return int(float(t[:-1]) * 1000) if t.endswith('k') else int(t)\n```"
    assert by_name["parse-miles"].score(good) == 1.0 and by_name["parse-miles"].score("def parse_miles(:") == 0.0
    assert bench.run_code_score(good, "parse_miles", by_name["parse-miles"].score.checks) == 1.0
    assert bench.run_code_score("def parse_miles(text):\n    return 0", "parse_miles", by_name["parse-miles"].score.checks) < 1.0


def test_leaderboard_and_best_value(hub, models):
    answers = {"zip": "34236", "missing-search": "2", "search-summary": "Kelley Blue Book led; Sarasota Ford ranked directly.",
               "gold-certified": "172-point inspection, under 6 years, under 80,000 miles.",
               "listing": '{"year":2019,"make":"Ford","model":"EcoSport","trim":"Titanium","miles":115176,"price":6799}',
               "dealer-address": '{"name":"Gulf Coast Auto Brokers of Sarasota","street":"4343 Clark Rd","city":"Sarasota","zip":"34233"}'}

    def good(messages):
        prompt = messages[-1]["content"]
        return next(answers[c.name] for c in bench.CASES if c.prompt == prompt and c.name in answers)

    cases = tuple(c for c in bench.CASES if c.name in answers)
    models.set("openai:small", good)
    models.set("anthropic:big", good)
    models.set("openai:mid", "I am not sure.")
    rows = bench.run(hub, ["openai:small", "anthropic:big", "openai:mid"], cases)
    board = bench.leaderboard(rows)
    assert board["quick"]["openai:small"]["score"] == 1.0 and board["quick"]["openai:mid"]["score"] == 0.0
    assert bench.best_value(rows)["quick"] == ["openai:small", "anthropic:big"]   # same score, cheaper first; the failing model is out
    assert "openai:small" in bench.table(rows)
    assert hub.memory.recent(5) == []                                              # bench runs are not saved to memory


def test_bench_records_errors(hub, models):
    models.set("openai:small", ProviderError("down"))
    models.set("anthropic:small", ProviderError("down"))
    rows = bench.run(hub, ["openai:small"], bench.CASES[:1])
    assert rows[0]["score"] == 0.0 and "down" in rows[0]["error"]


# --- HTTP server ---


@pytest.fixture
def client(hub):
    from starlette.testclient import TestClient

    from crossvet.chat.server import create_app

    return TestClient(create_app(hub, token=""))


def test_chat_completions_auto_routes_and_says_why(client, hub, models):
    r = client.post("/v1/chat/completions", json={"model": "auto", "messages": [
        {"role": "system", "content": "Be terse."}, {"role": "user", "content": "hi"}, {"role": "assistant", "content": "hello"},
        {"role": "user", "content": [{"type": "text", "text": "Fix this Python bug"}]}]}, headers={"x-crossvet-app": "open-webui"})
    data = r.json()
    assert r.status_code == 200 and data["choices"][0]["message"]["content"] == "answer from anthropic:big"
    assert data["model"] == "anthropic:big" and data["crossvet"]["slot"] == "strong" and "code task" in data["crossvet"]["why"]
    sent = models.calls[-1][1]
    assert sent[0]["content"].startswith("Be terse.") and [m["content"] for m in sent[1:]] == ["hi", "hello", "Fix this Python bug"]
    saved = hub.memory.recent(2)
    assert saved[0].author == "open-webui" and saved[0].model == "anthropic:big"


def test_chat_completions_slot_named_model_stream_and_errors(client, models):
    assert client.post("/v1/chat/completions", json={"model": "crossvet/quick", "messages": [{"role": "user", "content": "x"}]}
                       ).json()["model"] == "openai:small"
    assert client.post("/v1/chat/completions", json={"model": "xai:grok", "messages": [{"role": "user", "content": "x"}]}
                       ).json()["model"] == "xai:grok"
    stream = client.post("/v1/chat/completions", json={"model": "auto", "stream": True, "messages": [{"role": "user", "content": "x"}]})
    assert stream.headers["content-type"].startswith("text/event-stream") and stream.text.rstrip().endswith("data: [DONE]")
    assert client.post("/v1/chat/completions", json={"model": "crossvet/turbo", "messages": [{"role": "user", "content": "x"}]}).status_code == 400
    assert client.post("/v1/chat/completions", json={"messages": []}).status_code == 400
    models.set("xai:grok", ProviderError("HTTP 500"))
    assert client.post("/v1/chat/completions", json={"model": "xai:grok", "messages": [{"role": "user", "content": "x"}]}).status_code == 502


def test_models_turns_viewer_and_health(client, hub):
    ids = [m["id"] for m in client.get("/v1/models").json()["data"]]
    assert ids[0] == "auto" and "crossvet/strong" in ids and "anthropic:big" in ids
    hub.ask("What is the capital of Australia?")
    turns = client.get("/api/turns").json()
    assert turns["turns"][0]["role"] == "assistant" and "why" in turns["turns"][0]["meta"] and turns["spent_today"] > 0
    page = client.get("/")
    assert "Crossvet chat activity" in page.text and "textContent" in page.text and page.headers["x-frame-options"] == "DENY"
    assert client.get("/health").json()["status"] == "ok"


def test_token_is_required_when_set(hub):
    from starlette.testclient import TestClient

    from crossvet.chat.server import create_app, serve

    locked = TestClient(create_app(hub, token="s3cret"))
    assert locked.get("/v1/models").status_code == 401 and locked.get("/api/turns").status_code == 401
    assert locked.post("/v1/chat/completions", json={"messages": [{"role": "user", "content": "x"}]}).status_code == 401
    assert locked.get("/v1/models", headers={"Authorization": "Bearer s3cret"}).status_code == 200
    # the token only counts in the header: a URL would put it in logs and browser history
    assert locked.get("/api/turns?token=s3cret").status_code == 401
    page = locked.get("/")  # the page holds no data; its script reads the token after #
    assert page.status_code == 200 and "location.hash" in page.text and "s3cret" not in page.text
    assert page.headers["referrer-policy"] == "no-referrer"
    assert locked.get("/health").status_code == 200
    assert serve("0.0.0.0", 1) == 2   # no token in the environment: refuses a public address


def test_a_public_address_needs_a_long_token(monkeypatch, capsys):
    from crossvet.chat.server import serve

    monkeypatch.setenv("CROSSVET_CHAT_TOKEN", "short")
    assert serve("0.0.0.0", 1) == 2 and "at least 16 characters" in capsys.readouterr().err


def test_a_wrong_token_is_answered_slowly(hub, monkeypatch):
    import time

    from starlette.testclient import TestClient

    from crossvet.chat import server

    monkeypatch.setattr(server, "FAIL_DELAY_SECONDS", 0.3)
    locked = TestClient(server.create_app(hub, token="s3cret"))
    began = time.monotonic()
    assert locked.get("/v1/models", headers={"Authorization": "Bearer guess"}).status_code == 401
    assert time.monotonic() - began >= 0.3
    began = time.monotonic()
    assert locked.get("/v1/models", headers={"Authorization": "Bearer s3cret"}).status_code == 200
    assert time.monotonic() - began < 0.3


def test_a_bad_limit_is_a_400(hub):
    from starlette.testclient import TestClient

    from crossvet.chat.server import create_app

    client = TestClient(create_app(hub, token=""))
    assert client.get("/api/turns?limit=lots").status_code == 400
    assert client.get("/api/turns?limit=0").status_code == 200


# --- MCP tools ---


def test_mcp_tools_share_one_memory(hub, models):
    claude, chatgpt = tools(hub, app="claude"), tools(hub, app="chatgpt")
    assert set(claude) == {"ask", "ask_model", "compare_models", "challenge", "explain_route", "save_note", "load_context",
                           "search_memory", "recent_turns", "rate_answer", "handoff_submit", "handoff_result",
                           "handoff_status"}
    claude["save_note"]("launch-date", "March 3")
    seen = chatgpt["load_context"]("launch")
    assert seen["notes"] == [{"key": "launch-date", "content": "March 3", "saved_by": "claude", "tags": ""}] and "notice" in seen
    out = chatgpt["ask"]("What is the capital of Australia?")
    assert out["model"] == "openai:small" and out["slot"] == "quick" and out["thread"]
    assert claude["recent_turns"](2)[0]["by"] == "openai:small"
    assert claude["ask_model"]("xai:grok", "What is trending?")["model"] == "xai:grok"
    assert claude["explain_route"]("Fix this Python bug")["slot"] == "strong" and len(models.calls) == 2
    assert [r["model"] for r in claude["compare_models"]("x", ["openai:mid", "anthropic:big"])] == ["openai:mid", "anthropic:big"]
    assert chatgpt["search_memory"]("capital Australia")["turns"]
    models.set("openai:big", json.dumps({"objections": [], "assumptions": []}))
    assert claude["challenge"]("a plan", author_model="anthropic:big")["objections"] == []


def test_mcp_server_registers_the_tools(hub):
    import asyncio

    from crossvet.chat.mcp_server import build_server

    server = build_server(hub)
    listed = asyncio.run(server.list_tools())
    assert {"ask", "save_note", "challenge"} <= {t.name for t in listed}
    assert all(t.description for t in listed)


# --- command line ---


@pytest.fixture
def cli_hub(hub, monkeypatch):
    monkeypatch.setattr(cli, "_hub", lambda: hub)
    monkeypatch.setattr(cli, "load", lambda: hub.config)
    return hub


def test_cli_route_is_free_and_explains(cli_hub, models, capsys):
    assert cli.main(["route", "Fix", "this", "Python", "bug"]) == 0
    out = capsys.readouterr().out
    assert "code task" in out and "anthropic:big" in out and "next: openai:big" in out and models.calls == []
    assert cli.main(["route", "--json", "hello there"]) == 0
    assert json.loads(capsys.readouterr().out)["slot"] == "balanced"


def test_cli_ask_note_log_compare_challenge(cli_hub, models, capsys):
    assert cli.main(["note", "add", "launch-date", "March", "3"]) == 0
    assert cli.main(["ask", "When is the launch?"]) == 0
    io = capsys.readouterr()
    assert "answer from openai:small" in io.out and "[openai:small" in io.err and "thread" in io.err
    assert cli.main(["note", "list"]) == 0 and "[launch-date] March 3" in capsys.readouterr().out
    assert cli.main(["note", "search", "launch"]) == 0 and "note [launch-date]" in capsys.readouterr().out
    assert cli.main(["log"]) == 0 and "spent today" in capsys.readouterr().out
    thread = cli_hub.memory.threads()[0]["thread"]
    assert cli.main(["log", "--thread", thread, "--why"]) == 0 and "why: quick task" in capsys.readouterr().out
    assert cli.main(["compare", "pick a number", "-m", "openai:mid", "-m", "xai:grok"]) == 0
    assert "=== openai:mid" in capsys.readouterr().out
    models.set("anthropic:big", json.dumps({"objections": [{"claim": "The date is wrong", "severity": "high",
                                                           "failure_case": "The contract says the launch is on March 10, not March 3"}]}))
    assert cli.main(["challenge", "--thread", thread, "--reviewer", "openai:big"]) == 1   # same vendor as the author: refused
    capsys.readouterr()
    assert cli.main(["challenge", "--thread", thread]) == 0                                # picks another vendor itself
    assert "Fails when: The contract says" in capsys.readouterr().out


def test_cli_errors_have_exit_codes(cli_hub, models, capsys, monkeypatch):
    models.set("xai:grok", ProviderError("HTTP 500"))
    assert cli.main(["ask", "-m", "xai:grok", "hello"]) == 1 and "every model failed" in capsys.readouterr().err
    monkeypatch.setattr(cli, "_hub", lambda: Hub(config=parse({}), memory=Memory(":memory:"), caller=models))
    assert cli.main(["ask", "hello"]) == 3 and "crossvet chat init" in capsys.readouterr().err


def test_cli_init_doctor_bench(tmp_path, monkeypatch, capsys, hub, models):
    monkeypatch.chdir(tmp_path)
    for key in ("OPENAI_API_KEY", "ANTHROPIC_API_KEY", "CROSSVET_CHAT_CONFIG"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "k")
    assert cli.main(["init"]) == 0 and (tmp_path / "crossvet-chat.toml").exists()
    assert cli.main(["init"]) == 2                                   # does not overwrite
    assert cli.main(["doctor"]) == 0
    out = capsys.readouterr().out
    assert "openai:gpt-6-luna" in out and "all models are from one vendor" in out
    monkeypatch.setattr(cli, "_hub", lambda: hub)
    assert cli.main(["bench", "--dry-run", "-m", "openai:small"]) == 0 and "Nothing was sent" in capsys.readouterr().out
    models.set("openai:small", "34236")
    assert cli.main(["bench", "-m", "openai:small", "--apply", "--out", "rows.jsonl"]) == 0
    assert "updated" in capsys.readouterr().out and len((tmp_path / "rows.jsonl").read_text().splitlines()) == len(bench.CASES)
    assert 'quick = ["openai:small"]' in (tmp_path / "crossvet-chat.toml").read_text()


def test_env_file_is_read_without_overriding(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env").write_text("# comment\nFOO_TEST_KEY=abc\nEXISTING_KEY='new'\nEMPTY=\n")
    monkeypatch.setenv("EXISTING_KEY", "old")
    monkeypatch.delenv("FOO_TEST_KEY", raising=False)
    assert cli.load_env() == ["FOO_TEST_KEY"]
    import os

    assert os.environ["FOO_TEST_KEY"] == "abc" and os.environ["EXISTING_KEY"] == "old"
    monkeypatch.delenv("FOO_TEST_KEY")


def test_reply_default_cost_is_unknown():
    assert Reply(text="x", model="m").cost is None
    assert CONFIG["slots"]["quick"][0] == "openai:small"


def test_end_to_end_against_a_local_openai_compatible_server(tmp_path, monkeypatch, capsys):
    """The real path: config file, real HTTP call, routing, saving, logging. Only the model is a stand-in."""
    import threading
    from http.server import BaseHTTPRequestHandler, HTTPServer

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["content-length"])))
            text = f"{body['model']} says hello"
            payload = json.dumps({"choices": [{"message": {"content": text}, "finish_reason": "stop"}],
                                  "usage": {"prompt_tokens": 12, "completion_tokens": 4}}).encode()
            self.send_response(200)
            self.send_header("content-type", "application/json")
            self.send_header("content-length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def log_message(self, *args):
            pass

    server = HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv("LOCAL_BASE_URL", f"http://127.0.0.1:{server.server_port}/v1")
        monkeypatch.setenv("CROSSVET_CHAT_DB", str(tmp_path / "memory.db"))
        monkeypatch.delenv("CROSSVET_CHAT_CONFIG", raising=False)
        (tmp_path / "crossvet-chat.toml").write_text(
            '[slots]\nquick = ["local:tiny"]\nstrong = ["local:large"]\n[models."local:tiny"]\ncontext = 8000\ninput = 1.0\noutput = 2.0\n')
        assert cli.main(["doctor"]) == 0
        capsys.readouterr()
        assert cli.main(["ask", "What is the capital of Australia?"]) == 0
        io = capsys.readouterr()
        assert io.out.strip() == "tiny says hello" and "[local:tiny" in io.err and "$0.0000" in io.err
        assert cli.main(["ask", "Fix the race condition in this Go worker pool"]) == 0
        assert capsys.readouterr().out.strip() == "large says hello"
        assert cli.main(["log"]) == 0
        assert "2 turns" in capsys.readouterr().out
    finally:
        server.shutdown()


def test_strong_takes_the_newer_version_of_the_same_model():
    """An older version that costs more must not beat its newer successor for the strong slot."""
    catalog = [entry("anthropic/claude-haiku-5", 0.5, 2, age_days=20),
               entry("anthropic/claude-fable-5.1", 15, 75, age_days=60),
               entry("anthropic/claude-fable-5.2", 5, 25, age_days=10)]
    slots, _ = setup.from_catalog(catalog, now=NOW)
    assert slots["strong"] == ["openrouter:anthropic/claude-fable-5.2"]
    assert slots["balanced"] == ["openrouter:anthropic/claude-fable-5.2"]
    assert slots["quick"] == ["openrouter:anthropic/claude-haiku-5"]


def test_openai_gets_max_completion_tokens_and_passthrough_converts(monkeypatch):
    """Found by the live tests on 2026-11-25: OpenAI's current models refuse max_tokens."""
    monkeypatch.setenv("OPENAI_API_KEY", "k-test")
    bodies = []

    def handler(request: httpx.Request) -> httpx.Response:
        bodies.append(json.loads(request.content))
        return httpx.Response(200, json={"choices": [{"message": {"content": "hi"}, "finish_reason": "stop"}],
                                         "usage": {"prompt_tokens": 7, "completion_tokens": 3}})

    providers.call("openai:gpt-6-luna", [{"role": "user", "content": "hello"}], 50, transport(handler))
    assert bodies[-1]["max_completion_tokens"] == 50 and "max_tokens" not in bodies[-1]
    providers.passthrough("openai:gpt-6-luna", {"messages": [{"role": "user", "content": "hi"}], "max_tokens": 80,
                                                "stream": True}, transport(handler))
    assert bodies[-1]["max_completion_tokens"] == 80 and "max_tokens" not in bodies[-1] and "stream" not in bodies[-1]
    assert providers.limit_field("openrouter") == providers.limit_field("xai") == "max_tokens"
