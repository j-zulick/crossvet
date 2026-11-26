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
            return names, answer, recent

    names, answer, recent = asyncio.run(run())
    text = "".join(getattr(c, "text", "") for c in answer.content)
    log("mcp_stdio", None, model=model[0], tools=names, answer_start=text[:300])
    assert names == ["ask_model", "list_models", "recent_turns"]
    assert not getattr(answer, "is_error", getattr(answer, "isError", False)) and f"[crossvet: {model[0]}" in text
    assert model[0] in "".join(getattr(c, "text", "") for c in recent.content)
