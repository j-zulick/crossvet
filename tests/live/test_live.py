"""Live checks of the one-chat path, each on a real task from used-car dealer work in Sarasota, Florida.

Run with ``CROSSVET_LIVE=1 uv run pytest tests/live -q``. See conftest.py for the cap and the log.
"""

from __future__ import annotations

import asyncio
import base64
import json
import os
import struct
import sys
import time
import zlib

import pytest
from live_helpers import have, log, settings

from crossvet.chat.config import parse
from crossvet.chat.hub import BudgetExceeded, Hub
from crossvet.chat.memory import Memory

pytestmark = pytest.mark.skipif(os.environ.get("CROSSVET_LIVE") != "1",
                                reason="live tests call paid APIs; run with CROSSVET_LIVE=1")

DEALER_FACTS = (
    "On Nov 25, 2026, six searches for used cars in Sarasota, Florida were run: 'used car sales Sarasota Florida', "
    "'used cars Sarasota FL', 'used car dealers Sarasota FL', 'pre-owned cars for sale Sarasota', 'certified pre-owned "
    "Sarasota dealership' and 'cheap used cars Sarasota buy here pay here'. Kelley Blue Book and iSeeCars appeared in "
    "five each. Sarasota Ford's own site and Edmunds appeared in four each; Sarasota Ford's was the only dealer site that "
    "ranked directly. TrueCar appeared in three; Cars.com, Carfax, Autotrader and CarGurus in two each. Other dealers "
    "appeared only through marketplace or directory pages."
)


def both() -> None:
    if not (have("openai") and have("anthropic")):
        pytest.skip("needs both OPENAI_API_KEY and ANTHROPIC_API_KEY")


# --- every provider answers -------------------------------------------------------------------

@pytest.mark.parametrize("model", ["openai:gpt-6-luna", "anthropic:claude-haiku-5-5"])
def test_each_provider_answers(hub, model):
    if not have(model.split(":", 1)[0]):
        pytest.skip(f"no key for {model}")
    answer = hub.ask("In one sentence, what does 'certified pre-owned' mean at a car dealership?", model=model)
    log("each_provider_answers", answer)
    assert answer.model == model and len(answer.text.split()) >= 5
    assert answer.cost and answer.cost > 0 and answer.turn_id


# --- routing by kind of task ------------------------------------------------------------------

def test_routing_by_kind_of_task(hub):
    code = hub.ask("Write a Python function that parses a used-car listing title such as "
                   "'2021 Toyota Tacoma SR5 - 34,210 mi - $31,995' into year, make, model, trim, miles and price. "
                   "Return only the code.")
    log("routing_code", code)
    assert code.decision.task.kind == "code" and "def " in code.text
    quick = hub.ask("Is a 2019 Honda CR-V with 48,000 miles low or high mileage for its age? One sentence.")
    log("routing_quick", quick)
    writing = hub.ask("Write a two-sentence reply to a Sarasota shopper who asked whether the 2019 Honda CR-V "
                      "on our lot is still available. It is, and they can test drive it Saturday.")
    log("routing_writing", writing)
    assert writing.decision.task.kind == "writing"
    ladder = ["quick", "balanced", "strong"]
    assert ladder.index(quick.decision.slot) <= ladder.index(code.decision.slot)
    for answer in (code, quick, writing):
        assert answer.decision.explain() and answer.cost and answer.cost > 0


def test_named_model_and_retry_stronger(hub):
    first = hub.ask("Summarize in two sentences: " + DEALER_FACTS, model="openai:gpt-6-luna" if have("openai")
                    else "anthropic:claude-haiku-5-5")
    log("named_model", first)
    retried = hub.retry(first.thread, stronger=True)
    log("retry_stronger", retried)
    ladder = ["quick", "balanced", "strong"]
    assert retried.decision.slot in ladder and retried.text.strip()
    assert retried.decision.slot != first.decision.slot or retried.model != first.model


# --- the server, the way Hermes and other chat apps use it ------------------------------------

@pytest.fixture
def client(hub):
    from starlette.testclient import TestClient

    from crossvet.chat.server import create_app

    return TestClient(create_app(hub, token=""))


def test_server_answers_like_an_openai_api(client):
    response = client.post("/v1/chat/completions", json={
        "model": "auto",
        "messages": [{"role": "user", "content": "List three questions a shopper should ask before buying a used car "
                                                 "from an independent lot in Sarasota. Numbered list, no intro."}]})
    assert response.status_code == 200, response.text
    body = response.json()
    text = body["choices"][0]["message"]["content"]
    meta = body["crossvet"]
    log("server_openai_shape", None, model=meta.get("model"), slot=meta.get("slot"), kind=meta.get("kind"),
        cost_usd=meta.get("cost_usd", meta.get("cost")), answer_start=text[:300])
    assert "1" in text and meta.get("model")


def test_server_streams_and_slash_commands_work(client):
    thread = f"live-{int(time.time())}"
    pieces, final = [], None
    with client.stream("POST", "/v1/chat/completions", headers={"x-crossvet-thread": thread}, json={
            "model": "auto", "stream": True,
            "messages": [{"role": "user", "content": "In three short sentences, why might a dealer's own website rank "
                                                     "below Kelley Blue Book for 'used cars Sarasota FL'?"}]}) as response:
        assert response.status_code == 200
        for line in response.iter_lines():
            if not line.startswith("data: ") or line == "data: [DONE]":
                continue
            chunk = json.loads(line[6:])
            delta = (chunk.get("choices") or [{}])[0].get("delta", {}).get("content")
            if delta:
                pieces.append(delta)
            if chunk.get("crossvet"):
                final = chunk["crossvet"]
    text = "".join(pieces)
    log("server_streaming", None, chunks=len(pieces), model=(final or {}).get("model"), answer_start=text[:300])
    assert len(pieces) > 1 and len(text.split()) > 10 and final
    why = client.post("/v1/chat/completions", headers={"x-crossvet-thread": thread},
                      json={"model": "auto", "messages": [{"role": "user", "content": "/why"}]})
    why_text = why.json()["choices"][0]["message"]["content"]
    log("server_slash_why", None, answer_start=why_text[:300])
    assert why.status_code == 200 and ("slot" in why_text or "→" in why_text or "because" in why_text)


def _png_bar_chart(heights: list[int], width: int = 360, height: int = 220) -> bytes:
    """A bar chart as a PNG, drawn in pure Python (one bar per value, left to right)."""
    colors = [(31, 119, 180), (255, 127, 14), (44, 160, 44), (214, 39, 40), (148, 103, 189), (140, 86, 75)]
    top = max(heights)
    bar_w = width // (len(heights) * 2)
    rows = []
    for y in range(height):
        row = bytearray([0])
        for x in range(width):
            pixel = (255, 255, 255)
            i, offset = divmod(x - bar_w // 2, bar_w * 2)
            if 0 <= i < len(heights) and offset < bar_w and y >= height - 10 - int((height - 30) * heights[i] / top) and y < height - 10:
                pixel = colors[i % len(colors)]
            row.extend(pixel)
        rows.append(bytes(row))
    raw = zlib.compress(b"".join(rows), 9)

    def chunk(kind: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)

    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", raw) + chunk(b"IEND", b""))


def test_an_image_goes_to_the_vision_slot(client):
    png = _png_bar_chart([5, 5, 4, 4, 3, 2])  # searches each site appeared in: KBB, iSeeCars, Sarasota Ford, Edmunds, TrueCar, Cars.com
    data_url = "data:image/png;base64," + base64.b64encode(png).decode()
    response = client.post("/v1/chat/completions", json={"model": "auto", "messages": [{"role": "user", "content": [
        {"type": "text", "text": "This chart shows how many of six searches for used cars in Sarasota, Florida each "
                                 "website appeared in, one bar per website. Answer exactly in this form: "
                                 "bars=<number>; tallest=<how many bars share the greatest height>"},
        {"type": "image_url", "image_url": {"url": data_url}}]}]})
    assert response.status_code == 200, response.text
    body = response.json()
    text = body["choices"][0]["message"]["content"].lower().replace(" ", "")
    log("image_to_vision", None, model=body["crossvet"].get("model"), slot=body["crossvet"].get("slot"), answer_start=text[:200])
    assert body["crossvet"].get("slot") == "vision"
    assert "bars=6" in text and "tallest=2" in text


# --- the guard: spend caps and refused accounts -----------------------------------------------

def test_spend_cap_stops_a_call_before_it_is_made(tmp_path):
    if not (have("openai") or have("anthropic")):
        pytest.skip("needs a key")
    capped = Hub(parse(settings(max_usd_per_call=0.0000001)), Memory(str(tmp_path / "capped.db")))
    with pytest.raises(BudgetExceeded):
        capped.ask("Write a 300-word history of used-car sales in Florida.", slot="strong")
    log("spend_cap", None, result="refused before any model was called")
    assert capped.memory.recent(10) == [] or all(t.role == "user" for t in capped.memory.recent(10))


def test_a_refused_key_is_skipped_and_not_called_again(tmp_path, monkeypatch):
    both()
    monkeypatch.setenv("OPENAI_API_KEY", "sk-crossvet-live-test-not-a-real-key")
    guarded = Hub(parse(settings()), Memory(str(tmp_path / "refused.db")))
    first = guarded.ask("One sentence: what is a buy-here-pay-here dealership?", slot="quick")
    log("refused_account_first", first)
    assert first.model.startswith("anthropic:") and not first.attempts[0].ok and "openai" in guarded.refused_accounts
    second = guarded.ask("One sentence: what is a vehicle history report?", slot="quick")
    log("refused_account_second", second)
    assert second.model.startswith("anthropic:")
    assert all(a.seconds < 0.5 for a in second.attempts if a.model.startswith("openai:"))


# --- several models from one chat -------------------------------------------------------------

def test_compare_and_challenge_across_vendors(hub):
    both()
    from crossvet.chat.mcp_server import tools

    tool = tools(hub)
    answers = tool["compare_models"]("Give one tip, in one sentence, for a Sarasota used-car dealer whose own site "
                                     "ranks below marketplaces for 'used cars Sarasota FL'.",
                                     ["openai:gpt-6-luna", "anthropic:claude-haiku-5-5"])
    log("compare_models", None, models=[a.get("model") for a in answers], cost_usd=sum(a.get("cost_usd") or 0 for a in answers))
    assert all((a.get("cost_usd") or 0) > 0 for a in answers)
    assert len(answers) == 2 and all(a.get("text") for a in answers)
    work = ("Sarasota Ford's own site ranked in four of the six searches, so every other Sarasota dealer should copy its "
            "keyword pages.")
    result = tool["challenge"](work=work, request="Check this claim against the facts: " + DEALER_FACTS,
                               author_model="openai:gpt-6-luna")
    log("challenge", None, reviewer=result.get("reviewer"), objections=result.get("objections"), cost_usd=result.get("cost_usd"),
        problem=result.get("problem"))
    assert result["reviewer"].startswith("anthropic:") and not result.get("problem")


# --- ratings and Langfuse ---------------------------------------------------------------------

def test_a_rating_is_saved_and_reaches_langfuse(hub):
    answer = hub.ask("Draft a one-line text message to a customer whose 2018 Ford F-150 trade-in appraisal is ready.")
    hub.feedback(True, turn_id=answer.turn_id, comment="live test: good reply", source="live-test")
    log("rating", answer, rating="good")
    if not (os.environ.get("LANGFUSE_PUBLIC_KEY") and os.environ.get("LANGFUSE_SECRET_KEY")):
        pytest.skip("Langfuse keys not set; the rating is saved locally only")
    hub.recorder.flush()
    from datetime import UTC, datetime, timedelta

    import httpx

    from crossvet.chat.langfuse_sync import sync

    base = os.environ.get("LANGFUSE_BASE_URL") or os.environ.get("LANGFUSE_HOST") or "https://cloud.langfuse.com"
    auth = (os.environ["LANGFUSE_PUBLIC_KEY"], os.environ["LANGFUSE_SECRET_KEY"])
    trace_id = hub.trace_id(answer.turn_id)
    since = (datetime.now(UTC) - timedelta(minutes=10)).strftime("%Y-%m-%dT%H:%M:%SZ")
    generation, score = None, None
    for _ in range(20):  # observations are live in Langfuse; scores may lag by minutes
        response = httpx.get(f"{base}/api/public/v2/observations", auth=auth, timeout=20,
                             params={"fields": "core,basic,usage", "fromStartTime": since, "limit": 100})
        if response.status_code == 200:
            generation = next((o for o in response.json().get("data", []) if o.get("traceId") == trace_id), None)
        scores = httpx.get(f"{base}/api/public/v3/scores", auth=auth, timeout=20, params={"traceId": trace_id, "limit": 10})
        if scores.status_code == 200:
            score = next((x for x in scores.json().get("data", []) if x.get("name") == "user-feedback"), None)
        if generation and score:
            break
        time.sleep(5)
    synced = sync(hub, days=1)  # `crossvet chat sync`: reads ratings added in Langfuse (v3 scores API)
    log("langfuse", None, trace_id=trace_id, generation=bool(generation), model=(generation or {}).get("providedModelName"),
        rating_seen=bool(score), sync_fetched=synced.fetched, sync_imported=synced.imported)
    assert generation, f"trace {trace_id} has no generation in Langfuse"


# --- MCP over stdio, the way Cursor and Claude Code start it ----------------------------------

def test_mcp_server_over_stdio(tmp_path):
    if not (have("openai") or have("anthropic")):
        pytest.skip("needs a key")
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    toml = tmp_path / "crossvet-chat.toml"
    cfg = settings()
    lines = ["[slots]"] + [f"{k} = {json.dumps(v)}" for k, v in cfg["slots"].items()]
    lines += ["", "[limits]"] + [f"{k} = {v}" for k, v in cfg["limits"].items()]
    for model, info in cfg["models"].items():
        lines += ["", f'[models."{model}"]'] + [f"{k} = {v}" for k, v in info.items()]
    toml.write_text("\n".join(lines) + "\n")
    env = {**os.environ, "CROSSVET_CHAT_CONFIG": str(toml), "CROSSVET_CHAT_DB": str(tmp_path / "mcp.db")}
    params = StdioServerParameters(command=sys.executable, args=["-c", "from crossvet.chat.cli import main; main(['mcp'])"],
                                   env=env)

    async def run():
        async with stdio_client(params) as (read, write), ClientSession(read, write) as session:
            await session.initialize()
            names = sorted(t.name for t in (await session.list_tools()).tools)
            route = await session.call_tool("explain_route", {"request": "Fix the bug in this inventory CSV import script"})
            answer = await session.call_tool("ask", {"request": "In one sentence, what should a used-car listing title include?"})
            return names, route, answer

    names, route, answer = asyncio.run(run())
    answer_text = "".join(getattr(c, "text", "") for c in answer.content)
    log("mcp_stdio", None, tools=names, route="".join(getattr(c, "text", "") for c in route.content)[:300],
        answer_start=answer_text[:300])
    assert {"ask", "ask_model", "compare_models", "challenge", "explain_route", "rate_answer"} <= set(names)
    assert not answer.isError and answer_text.strip()
