"""Live checks with real API keys, each on a real task from used-car dealer work in Sarasota, Florida.

They call paid APIs, so they run only with ``CROSSVET_LIVE=1``:

    CROSSVET_LIVE=1 uv run pytest tests/live -q -rs

Keys come from the environment, ``./.env`` or ``~/.config/crossvet/.env``. Spend is capped at
USD 1 a day and USD 0.25 a call inside the tests. Each answer adds one line to ``CROSSVET_LIVE_LOG``
(default ``live-run.jsonl``): the test, model, tokens, cost, seconds and the start of the answer;
``docs/live-runs/`` is written from that file.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import time
from pathlib import Path

import pytest

from crossvet import providers
from crossvet.config import KNOWN, Config, load_env, parse
from crossvet.core import BudgetExceeded, Crossvet
from crossvet.providers import AccountError
from crossvet.store import Store

load_env()
pytestmark = pytest.mark.skipif(os.environ.get("CROSSVET_LIVE") != "1",
                                reason="live tests call paid APIs; run with CROSSVET_LIVE=1")
LOG = Path(os.environ.get("CROSSVET_LIVE_LOG", "live-run.jsonl"))
MILEAGE = "Is a 2019 Honda CR-V with 48,000 miles low or high mileage for its age? Answer in one sentence."
PARSE = ("Write a Python function parse_listing(s) that turns '2021 Toyota Tacoma SR5 - 34,210 mi - $31,995' into a dict "
         "with year, make, model, trim, miles and price. Code only.")
VIN_TOOL = {"type": "function", "function": {
    "name": "lookup_vin", "description": "Look up a vehicle by its 17-character VIN in the dealer's inventory.",
    "parameters": {"type": "object", "properties": {"vin": {"type": "string"}}, "required": ["vin"]}}}


def have(provider: str) -> bool:
    return providers.available(provider)


def ready(*models: str) -> list[str]:
    return [m for m in models if have(m.split(":", 1)[0])]


def settings(**limits: float) -> Config:
    usable = ready(*KNOWN)
    names = {short: m for m in usable for short in KNOWN[m][2]}
    default = next((m for m in ("anthropic:claude-haiku-5-5", "openai:gpt-6-luna") if m in usable), "")
    return parse({"default_model": default, "models": usable, "names": names,
                  "limits": {"max_usd_per_day": 1.0, "max_usd_per_call": 0.25, "max_output_tokens": 1500, **limits}})


def log(test: str, answer=None, **extra) -> None:
    row = {"test": test, "time": time.strftime("%Y-%m-%dT%H:%M:%S%z")}
    if answer is not None:
        row.update(model=answer.model, served_by=answer.served_by, input_tokens=answer.input_tokens,
                   output_tokens=answer.output_tokens, cost_usd=answer.cost, seconds=answer.seconds,
                   answer_start=(answer.text or json.dumps(answer.tool_calls))[:300])
    row.update(extra)
    with LOG.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row) + "\n")


@pytest.fixture
def cv(tmp_path):
    if not ready(*KNOWN):
        pytest.skip("needs OPENAI_API_KEY or ANTHROPIC_API_KEY")
    return Crossvet(settings(), Store(str(tmp_path / "live.db")))


# --- each model answers when named ---------------------------------------------------------------

@pytest.mark.parametrize("model", list(KNOWN))
def test_each_named_model_answers(cv, model):
    if not ready(model):
        pytest.skip(f"no key for {model}")
    answer = cv.ask(model, [{"role": "user", "content": MILEAGE}], app="live")
    log("named_model", answer)
    assert answer.model == model and answer.text.strip() and answer.output_tokens > 0 and answer.cost > 0


# --- the server, the way Hermes and other OpenAI-style apps use it ---------------------------------

@pytest.fixture
def client(cv):
    from starlette.testclient import TestClient

    from crossvet.server import create_app

    return TestClient(create_app(cv, token=""))


def test_server_model_menu_then_switch_with_slash_model(client):
    pick = ready("anthropic:claude-opus-5-5", "openai:gpt-6.1-sol")
    switch = ready("openai:gpt-6-luna", "anthropic:claude-haiku-5-5")
    if not (pick and switch):
        pytest.skip("needs a key")
    ids = [m["id"] for m in client.get("/v1/models").json()["data"]]
    assert pick[0] in ids
    first = client.post("/v1/chat/completions", json={"model": pick[0], "messages": [{"role": "user", "content": PARSE}]})
    assert first.status_code == 200, first.text
    data = first.json()
    log("server_named", None, model=data["model"], cost_usd=data["crossvet"]["cost"], answer_start=data["choices"][0]["message"]["content"][:300])
    assert data["model"] == pick[0] and "def parse_listing" in data["choices"][0]["message"]["content"]
    history = [{"role": "user", "content": PARSE}, data["choices"][0]["message"], {"role": "user", "content": f"/model {switch[0]}"}]
    switched = client.post("/v1/chat/completions", json={"model": pick[0], "messages": history}).json()
    history += [switched["choices"][0]["message"], {"role": "user", "content": MILEAGE}]
    second = client.post("/v1/chat/completions", json={"model": pick[0], "messages": history, "stream": True})
    events = [json.loads(line[6:]) for line in second.text.splitlines() if line.startswith("data: {")]
    text = "".join(e["choices"][0]["delta"].get("content", "") for e in events)
    log("server_switched_streamed", None, model=events[-1]["model"], cost_usd=events[-1]["crossvet"]["cost"], answer_start=text[:300])
    assert events[-1]["crossvet"]["model"] == switch[0] and text.strip()
    cost = client.post("/v1/chat/completions", json={"messages": history + [{"role": "user", "content": "/cost"}]}).json()
    report = cost["choices"][0]["message"]["content"]
    log("server_cost", None, answer_start=report[:300])
    assert pick[0] in report and switch[0] in report


@pytest.mark.parametrize("model", ["anthropic:claude-sonnet-5-5", "openai:gpt-6.1-sol", "openai:gpt-6-luna"])
def test_an_agents_tool_call_round_trip(client, model):
    """What Hermes does: send tools, get a tool call, send the result, get the answer."""
    if not ready(model):
        pytest.skip(f"no key for {model}")
    messages = [{"role": "system", "content": "You help a Sarasota used-car dealer. Use tools for inventory facts."},
                {"role": "user", "content": "What is the price of VIN 1FTFW1E80MFA12345? Use the tool."}]
    first = client.post("/v1/chat/completions", json={"model": model, "messages": messages, "tools": [VIN_TOOL]})
    assert first.status_code == 200, first.text
    message = first.json()["choices"][0]["message"]
    calls = message.get("tool_calls") or []
    log("tool_call", None, model=model, tool_calls=[c["function"]["name"] for c in calls], cost_usd=first.json()["crossvet"]["cost"])
    assert calls and calls[0]["function"]["name"] == "lookup_vin"
    result = {"role": "tool", "tool_call_id": calls[0]["id"],
              "content": json.dumps({"vin": "1FTFW1E80MFA12345", "vehicle": "2021 Ford F-150 XLT", "price": 38995})}
    final = client.post("/v1/chat/completions",
                        json={"model": model, "messages": [*messages, message, result], "tools": [VIN_TOOL]}).json()
    text = final["choices"][0]["message"]["content"] or ""
    log("tool_result_answer", None, model=model, cost_usd=final["crossvet"]["cost"], answer_start=text[:300])
    assert "38,995" in text or "38995" in text


def _stream(client, body):
    """POST a streaming request; return the chat chunks."""
    response = client.post("/v1/chat/completions", json={**body, "stream": True})
    assert response.status_code == 200, response.text
    return [json.loads(line[6:]) for line in response.text.splitlines() if line.startswith("data: {")]


def _assemble(chunks):
    """Rebuild the assistant message from streamed chunks, the way an agent does."""
    text, calls = "", {}
    for c in chunks:
        for choice in c.get("choices") or []:
            delta = choice.get("delta") or {}
            text += delta.get("content") or ""
            for call in delta.get("tool_calls") or []:
                kept = calls.setdefault(call["index"], {"id": "", "type": "function", "function": {"name": "", "arguments": ""}})
                kept["id"] = call.get("id") or kept["id"]
                kept["function"]["name"] = (call.get("function") or {}).get("name") or kept["function"]["name"]
                kept["function"]["arguments"] += (call.get("function") or {}).get("arguments") or ""
    message = {"role": "assistant", "content": text or None}
    if calls:
        message["tool_calls"] = [calls[i] for i in sorted(calls)]
    return message


@pytest.mark.parametrize("model", ["anthropic:claude-sonnet-5-5", "openai:gpt-6.1-sol"])
def test_a_streamed_agent_loop_with_parallel_tool_calls(client, model):
    """Hermes streams: two VINs looked up in one turn, results sent back, then the comparison, all streamed."""
    if not ready(model):
        pytest.skip(f"no key for {model}")
    prices = {"1FTFW1E80MFA12345": 38995, "5J6RW2H89KL004321": 27450}
    messages = [{"role": "system", "content": "You help a Sarasota used-car dealer. Use tools for inventory facts."},
                {"role": "user", "content": "Look up VINs 1FTFW1E80MFA12345 and 5J6RW2H89KL004321 and tell me which costs less."}]
    for step in range(3):
        chunks = _stream(client, {"model": model, "messages": messages, "tools": [VIN_TOOL]})
        message = _assemble(chunks)
        log("streamed_agent_step", None, model=model, step=step, cost_usd=chunks[-1]["crossvet"]["cost"],
            tool_calls=[json.loads(c["function"]["arguments"]).get("vin") for c in message.get("tool_calls", [])],
            answer_start=(message["content"] or "")[:200])
        if not message.get("tool_calls"):
            break
        messages.append(message)
        for call in message["tool_calls"]:
            vin = json.loads(call["function"]["arguments"]).get("vin", "")
            messages.append({"role": "tool", "tool_call_id": call["id"], "content": json.dumps({"vin": vin, "price": prices.get(vin)})})
    assert not message.get("tool_calls") and "27,450" in (message["content"] or "").replace("27450", "27,450")
    looked_up = {json.loads(c["function"]["arguments"]).get("vin") for m in messages for c in m.get("tool_calls", [])}
    assert looked_up == set(prices)


def test_openai_reasoning_is_kept_across_tool_steps(cv, client):
    """At high effort the model reasons before calling a tool; that reasoning goes back with the result."""
    model = "openai:gpt-6.1-sol"
    if not ready(model):
        pytest.skip("needs OPENAI_API_KEY")
    messages = [{"role": "user", "content": "A buyer has $30,000 and wants the lowest cost per remaining mile (200,000-mile life). "
                                            "Decide which one VIN to check first among 1FTFW1E80MFA12345 (2021 F-150) and "
                                            "5J6RW2H89KL004321 (2019 CR-V), reason it through, then look it up."}]
    body = {"model": model, "messages": messages, "tools": [VIN_TOOL], "reasoning_effort": "high", "max_completion_tokens": 3000}
    first = client.post("/v1/chat/completions", json=body).json()
    message = first["choices"][0]["message"]
    kept = cv.store.db.execute("SELECT COUNT(*) FROM relay_state").fetchone()[0]
    calls = message.get("tool_calls") or []
    assert calls, first
    results = [{"role": "tool", "tool_call_id": c["id"], "content": json.dumps({"price": 27450, "miles": 52000})} for c in calls]
    second = client.post("/v1/chat/completions", json={**body, "messages": [*messages, message, *results]})
    assert second.status_code == 200, second.text
    log("reasoning_kept", None, model=model, kept_items=kept, cost_usd=(first["crossvet"]["cost"] or 0) + (second.json()["crossvet"]["cost"] or 0),
        answer_start=(second.json()["choices"][0]["message"]["content"] or "")[:200])


def test_fields_without_a_place_are_reported(client):
    model = "openai:gpt-6-luna"
    if not ready(model):
        pytest.skip("needs OPENAI_API_KEY")
    data = client.post("/v1/chat/completions", json={"model": model, "seed": 7, "tools": [VIN_TOOL],
                                                      "messages": [{"role": "user", "content": "Say OK."}]}).json()
    log("dropped_fields", None, model=model, dropped=data["crossvet"].get("dropped"))
    assert data["crossvet"]["dropped"] == ["seed"]


# --- guards ---------------------------------------------------------------------------------------

def test_the_per_call_cap_stops_a_call_before_it_is_made(tmp_path):
    model = ready("anthropic:claude-opus-5-5", "openai:gpt-6.1-sol")
    if not model:
        pytest.skip("needs a key")
    cv = Crossvet(settings(max_usd_per_call=0.0001), Store(str(tmp_path / "cap.db")))
    with pytest.raises(BudgetExceeded):
        cv.ask(model[0], [{"role": "user", "content": MILEAGE}])
    log("per_call_cap", None, model=model[0], stopped=True)
    assert cv.store.recent() == []


def test_a_rejected_key_is_not_called_again(tmp_path, monkeypatch):
    if not have("anthropic"):
        pytest.skip("needs ANTHROPIC_API_KEY")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-not-a-real-key")
    cv = Crossvet(settings(), Store(str(tmp_path / "bad.db")))
    with pytest.raises(AccountError):
        cv.ask("anthropic:claude-haiku-5-5", [{"role": "user", "content": MILEAGE}])
    with pytest.raises(AccountError, match="not called again"):
        cv.ask("anthropic:claude-haiku-5-5", [{"role": "user", "content": MILEAGE}])
    log("rejected_key", None, provider="anthropic", refused=sorted(cv.refused))


# --- MCP over stdio, the way Claude Code, Codex and Cursor start it -------------------------------

def test_mcp_server_over_stdio(tmp_path):
    model = ready("openai:gpt-6-luna", "anthropic:claude-haiku-5-5")
    if not model:
        pytest.skip("needs a key")
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    env = {**os.environ, "CROSSVET_DB": str(tmp_path / "mcp.db"), "CROSSVET_CONFIG": str(tmp_path / "crossvet.toml")}
    (tmp_path / "crossvet.toml").write_text(f'default_model = "{model[0]}"\n')
    params = StdioServerParameters(command=sys.executable, args=["-c", "from crossvet.cli import main; main(['mcp'])"], env=env)

    async def run():
        async with stdio_client(params) as (read, write), ClientSession(read, write) as session:
            await session.initialize()
            names = sorted(t.name for t in (await session.list_tools()).tools)
            answer = await session.call_tool("ask_model", {"request": "In one sentence, what should a used-car listing "
                                                                      "title include?", "model": model[0]})
            recent = await session.call_tool("recent_turns", {"limit": 2})
            route = await session.call_tool("explain_route", {"request": "Fix the race condition in this Go worker pool"})
            return names, answer, recent, route

    names, answer, recent, route = asyncio.run(run())
    text = "".join(getattr(c, "text", "") for c in answer.content)
    log("mcp_stdio", None, model=model[0], tools=names, answer_start=text[:300])
    from crossvet.mcp_server import tools

    assert names == sorted(tools(Crossvet(settings(), Store())))
    assert "Kind of task: code" in "".join(getattr(c, "text", "") for c in route.content)
    assert not getattr(answer, "is_error", getattr(answer, "isError", False)) and f"[crossvet: {model[0]}" in text
    assert model[0] in "".join(getattr(c, "text", "") for c in recent.content)


# --- 3.0: auto, escalation, compare, challenge, the benchmark ------------------------------------------

def auto_settings(**slots: list[str]) -> Config:
    from crossvet.config import DEFAULT_SLOTS

    cfg = settings()
    cfg.slots = {k: ready(*v) for k, v in DEFAULT_SLOTS.items() if ready(*v)}
    cfg.slots.update(slots)
    return cfg


def test_auto_picks_a_slot_by_kind_and_explains(tmp_path):
    if not ready(*KNOWN):
        pytest.skip("needs a key")
    cv = Crossvet(auto_settings(), Store(str(tmp_path / "auto.db")))
    quick = cv.ask("auto", [{"role": "user", "content": "Sarasota Ford is at 707 S Washington Blvd., Sarasota, FL 34236. "
                                                         "What is its ZIP code? Number only."}])
    assert quick.decision["slot"] == "quick" and "34236" in quick.text
    log("auto_quick", quick, slot=quick.decision["slot"], reason=quick.decision["reason"])
    code = cv.ask("auto", [{"role": "user", "content": PARSE}])
    assert code.decision["slot"] == "strong" and "def parse_listing" in code.text
    log("auto_code", code, slot=code.decision["slot"], reason=code.decision["reason"])


def test_auto_escalates_past_a_model_that_fails(tmp_path):
    first = ready("openai:gpt-6-luna", "anthropic:claude-haiku-5-5")
    if not first:
        pytest.skip("needs a key")
    broken = ("openai:" if first[0].startswith("openai") else "anthropic:") + "no-such-model-crossvet"
    cv = Crossvet(auto_settings(quick=[broken, first[0]]), Store(str(tmp_path / "esc.db")))
    answer = cv.ask("auto", [{"role": "user", "content": MILEAGE}])
    steps = answer.decision["steps"]
    assert steps[0]["model"] == broken and steps[0]["outcome"].startswith("error") and answer.model == first[0]
    log("auto_escalation", answer, steps=steps)


def test_compare_and_a_cross_vendor_challenge(tmp_path):
    pair = ready("openai:gpt-6-luna", "anthropic:claude-haiku-5-5")
    if len(pair) < 2:
        pytest.skip("needs both OpenAI and Anthropic keys")
    from crossvet import multi

    cv = Crossvet(auto_settings(reviewer=ready("anthropic:claude-sonnet-5-5", "openai:gpt-6.1-terra")),
                  Store(str(tmp_path / "multi.db")))
    rows = multi.compare(cv, pair, MILEAGE)
    assert all(r.answer and r.answer.text for r in rows)
    for row in rows:
        log("compare", row.answer)
    result = multi.challenge(cv, MILEAGE, "48,000 miles is very high for a 2019 CR-V; most have under 20,000.",
                             author="openai:gpt-6-luna")
    assert result.verdict in ("wrong", "unsure") and result.challenger.startswith("anthropic:")
    log("challenge", result.answer, verdict=result.verdict, problems=result.problems)


def test_the_benchmark_scores_real_answers(tmp_path):
    models = ready("openai:gpt-6-luna", "anthropic:claude-haiku-5-5")
    if not models:
        pytest.skip("needs a key")
    from crossvet import bench

    cv = Crossvet(settings(), Store(str(tmp_path / "bench.db")))
    rows = bench.run(cv, models, bench.CASES[:4])
    assert all(not r["error"] for r in rows) and sum(r["score"] for r in rows) / len(rows) >= 0.5
    log("bench", None, rows=[{k: r[k] for k in ("model", "case", "score", "cost")} for r in rows])


# --- 3.1: a second-vendor review ---------------------------------------------------------------------

def test_a_reviewer_from_another_vendor_catches_a_planted_bug(tmp_path):
    if len(ready("openai:gpt-6.1-sol", "anthropic:claude-sonnet-5-5")) < 2:
        pytest.skip("needs both OpenAI and Anthropic keys")
    from crossvet import review, review_bench

    case = next(c for c in review_bench.CASES if c.name == "token-check")
    cv = Crossvet(auto_settings(reviewer=["anthropic:claude-sonnet-5-5", "openai:gpt-6.1-sol"]), Store(str(tmp_path / "rev.db")))
    result = review.run(cv, case.diff(), case.task, author="openai:gpt-6.1-sol", record_dir=tmp_path / "reviews")
    near = [f for f in result.kept if f.file == case.path and abs(f.line - case.line) <= 1]
    log("review", None, model=result.reviewer, cost_usd=result.cost, kept=len(result.kept),
        dropped=len(result.findings) - len(result.kept), caught=bool(near),
        answer_start="; ".join(f"{f.file}:{f.line} {f.severity} {f.problem}" for f in result.kept)[:300])
    assert result.reviewer == "anthropic:claude-sonnet-5-5" and near


# --- 3.2: a judge from another vendor, a shadow answer -------------------------------------------------

def test_a_judge_from_another_vendor_scores_real_answers(tmp_path):
    if len(ready("openai:gpt-6-luna", "anthropic:claude-haiku-5-5", "anthropic:claude-sonnet-5-5")) < 3:
        pytest.skip("needs both OpenAI and Anthropic keys")
    from crossvet import score

    cfg = auto_settings(quick=["openai:gpt-6-luna"])
    cfg.score_enabled, cfg.score_sample, cfg.score_judge = True, 1.0, "anthropic:claude-sonnet-5-5"
    cfg.score_shadow, cfg.score_shadow_sample, cfg.score_shadow_model = True, 1.0, "openai:gpt-6-luna"
    cv = Crossvet(cfg, Store(str(tmp_path / "score.db")))
    first = cv.ask("anthropic:claude-haiku-5-5", [{"role": "user", "content": MILEAGE}], app="terminal")
    summary = score.run(cv, limit=5, force_all=True)
    row = cv.lab.db.execute("SELECT * FROM scores WHERE turn_id = ?", (first.turn_id,)).fetchone()
    assert "Judged 1" in summary and row["score"] in (1, 2, 3, 4, 5) and row["judge"] == "openai:gpt-6.1-sol"
    log("judge", None, model=row["judge"], judged=first.model, score=row["score"], why=row["why"], cost_usd=row["cost"])
    shadow = score.shadow(cv, limit=1)
    cheap = cv.lab.db.execute("SELECT * FROM scores WHERE shadow_of = ?", (first.turn_id,)).fetchone()
    assert "1 shadow answer(s) judged" in shadow and cheap["model"] == "openai:gpt-6-luna"
    assert cheap["judge"] == "anthropic:claude-sonnet-5-5"
    log("shadow", None, model=cheap["model"], judge=cheap["judge"], score=cheap["score"], original=row["score"],
        why=cheap["why"], cost_usd=cheap["cost"])


# --- 3.3: routing from judged scores ----------------------------------------------------------------

def test_auto_routes_from_real_judged_answers(tmp_path):
    pair = ready("openai:gpt-6-luna", "anthropic:claude-haiku-5-5")
    if len(pair) < 2:
        pytest.skip("needs both OpenAI and Anthropic keys")
    from crossvet import score

    cfg = auto_settings(quick=pair)
    cfg.score_enabled, cfg.score_sample = True, 1.0
    cfg.router_use, cfg.min_scores, cfg.explore = "scores", 2, 0.0
    cv = Crossvet(cfg, Store(str(tmp_path / "routescore.db")))
    questions = ["Sarasota Ford is at 707 S Washington Blvd., Sarasota, FL 34236. What is its ZIP code? Number only.",
                 "Gulf Coast Auto Brokers is at 4343 Clark Rd, Sarasota, FL 34233. What is its ZIP code? Number only."]
    for model in pair:
        for question in questions:
            cv.ask(model, [{"role": "user", "content": question}], app="terminal")
    assert "Judged 4" in score.run(cv, limit=4, force_all=True)
    board = score.leaderboard(cv, 1)["quick"]
    decision = cv.decide("auto", [{"role": "user", "content": questions[0]}])
    assert decision.reason.count("scores:") == 1 and decision.model in pair
    answer = cv.ask("auto", [{"role": "user", "content": questions[1]}])
    assert answer.model == decision.model and "34233" in answer.text
    log("route_from_scores", answer, board={m: {k: c[k] for k in ("n", "score", "low")} for m, c in board.items()},
        reason=decision.reason, judge_cost=sum(r["cost"] for r in cv.lab.db.execute("SELECT cost FROM scores").fetchall()))


# --- 3.4: the server as a long-running process ------------------------------------------------------

def test_the_server_process_answers_auto_over_http(tmp_path):
    if not ready("openai:gpt-6-luna", "anthropic:claude-haiku-5-5"):
        pytest.skip("needs a key")
    import socket
    import subprocess
    import urllib.request

    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    env = {**os.environ, "CROSSVET_DB": str(tmp_path / "svc.db"), "CROSSVET_CONFIG": ""}
    server = subprocess.Popen([sys.executable, "-c", f"from crossvet.cli import main; main(['serve', '--port', '{port}'])"],
                              env=env, cwd=tmp_path, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    try:
        for _ in range(50):
            try:
                health = json.loads(urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=1).read())
                break
            except OSError:
                time.sleep(0.2)
        else:
            pytest.fail("the server did not start: " + (server.stderr.read(2000) if server.stderr else b"").decode())
        body = json.dumps({"model": "auto", "messages": [{"role": "user", "content": "Sarasota Ford is at 707 S Washington "
                                                          "Blvd., Sarasota, FL 34236. What is its ZIP code? Number only."}]}).encode()
        request = urllib.request.Request(f"http://127.0.0.1:{port}/v1/chat/completions", data=body,
                                         headers={"content-type": "application/json"})
        reply = json.loads(urllib.request.urlopen(request, timeout=60).read())
    finally:
        server.terminate()
        server.wait(timeout=10)
    text = reply["choices"][0]["message"]["content"]
    from crossvet import __version__

    assert health["status"] == "ok" and health["version"] == __version__
    assert "34236" in text and reply["crossvet"]["decision"]["slot"] == "quick"
    log("server_process", None, model=reply["model"], cost_usd=reply["crossvet"]["cost"], version=health["version"],
        slot=reply["crossvet"]["decision"]["slot"], answer_start=text[:100])


# --- 3.6.1: Langfuse sync on Langfuse v4 ------------------------------------------------------------

def test_langfuse_sync_lands_as_a_generation_with_its_rating(tmp_path):
    from crossvet import langfuse

    if not langfuse.configured() or not ready("anthropic:claude-haiku-5-5"):
        pytest.skip("needs LANGFUSE_PUBLIC_KEY, LANGFUSE_SECRET_KEY and an Anthropic key")

    cv = Crossvet(settings(), Store(str(tmp_path / "lf.db")))
    answer = cv.ask("anthropic:claude-haiku-5-5", [{"role": "user", "content": "Sarasota Ford is at 707 S Washington Blvd., "
                                                    "Sarasota, FL 34236. What is its ZIP code? Number only."}], app="live")
    cv.lab.rate(answer.turn_id, 1, "correct ZIP")
    summary = langfuse.sync(cv)
    assert "Sent 1 answer(s) and 1 score(s)" in summary
    tid = langfuse.trace_id(cv, answer.turn_id)
    seen, rating = None, None
    with langfuse._client(None) as client:
        for _ in range(6):  # Langfuse ingests asynchronously; it usually shows within 10 seconds
            time.sleep(5)
            obs = client.get("/api/public/v2/observations",
                             params={"traceId": tid, "limit": 5, "fields": "core,basic,io,model,usage"})
            scores = client.get("/api/public/v3/scores", params={"name": "user_rating", "limit": 50, "fields": "subject"})
            seen = next(iter(obs.json().get("data") or []), None) if obs.status_code == 200 else None
            rating = next((s for s in (scores.json().get("data") or []) if (s.get("subject") or {}).get("id") == tid), None) \
                if scores.status_code == 200 else None
            if seen and rating:
                break
    assert isinstance(seen, dict) and seen["type"] == "GENERATION" and seen["model"] == answer.model
    assert seen["usageDetails"]["input"] == answer.input_tokens and seen["output"] == answer.text
    assert rating and rating["value"] == 1
    log("langfuse_sync", answer, trace=tid, landed_model=seen["model"], landed_usage=seen["usageDetails"],
        landed_cost=seen.get("totalCost"), rating=rating["value"])
