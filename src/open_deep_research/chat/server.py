"""An OpenAI-compatible HTTP server in front of the chat hub, plus a page that shows what happened.

Point any app that speaks the OpenAI chat API at ``http://127.0.0.1:8787/v1`` and pick the
model ``auto``: each request is classified, routed and answered. Other model names:

    auto                 the router decides
    crossvet/<slot>      quick, balanced, strong, fresh, long or reviewer
    provider:model       that exact model

The header ``x-crossvet-router`` overrides the router for one request (rules, jev,
openrouter-auto, openrouter-auto-code, jev-router).

Agents keep their tools: a request with ``tools`` (or with tool results) is routed on its latest
user message and passed through to the chosen model unchanged; a tool loop stays on the model
that started it.

A few commands work from any chat app, typed as the whole message (no model is called):

    /why                 why the last answer in this conversation went to that model
    /retry stronger      ask the last question again, one slot up
    /good, /bad [note]   rate the last answer (also POST /api/feedback)

Security: it binds to localhost by default. Set ``CROSSVET_CHAT_TOKEN`` to require
``Authorization: Bearer <token>``; binding to any other address without a token is refused.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import time
from typing import Any

from open_deep_research.chat import __version__
from open_deep_research.chat.config import SLOTS
from open_deep_research.chat.hub import Answer, BudgetExceeded, Hub, NoModel, user_text
from open_deep_research.chat.providers import ProviderError

LOCAL_HOSTS = ("127.0.0.1", "localhost", "::1")
PREFIX = "crossvet/"
VIEWER = """<!doctype html><meta charset="utf-8"><title>Crossvet chat activity</title>
<style>body{font:14px system-ui;margin:2rem auto;max-width:60rem;padding:0 1rem;color:#222}
.t{border-top:1px solid #ddd;padding:.6rem 0}.m{color:#666;font-size:12px}.c{white-space:pre-wrap;margin:.3rem 0}
.user .c{font-weight:600}.why{color:#555;font-size:12px}</style>
<h1>Crossvet chat activity</h1><p class="m">Newest first. Refreshes every 5 seconds. <span id="spent"></span></p><div id="turns"></div>
<script>
const token = new URLSearchParams(location.search).get("token");
async function load(){
  const r = await fetch("/api/turns?limit=60", {headers: token ? {Authorization: "Bearer " + token} : {}});
  if(!r.ok){document.getElementById("turns").textContent = "HTTP " + r.status; return;}
  const data = await r.json(); const box = document.getElementById("turns"); box.replaceChildren();
  document.getElementById("spent").textContent = "Spent today: $" + data.spent_today.toFixed(4);
  for(const t of data.turns){
    const d = document.createElement("div"); d.className = "t " + t.role;
    const m = document.createElement("div"); m.className = "m";
    m.textContent = [new Date(t.ts*1000).toLocaleTimeString(), t.role, t.model || t.author, "thread " + t.thread,
                     t.cost == null ? "" : "$" + t.cost.toFixed(4)].filter(Boolean).join(" · ");
    const c = document.createElement("div"); c.className = "c"; c.textContent = t.content;
    d.append(m, c);
    if(t.meta && t.meta.why){const w = document.createElement("div"); w.className = "why"; w.textContent = "Why: " + t.meta.why; d.append(w);}
    box.append(d);
  }
}
load(); setInterval(load, 5000);
</script>"""


def resolve_model(name: str) -> tuple[str | None, str | None]:
    """Turn the request's model name into ``(model, slot)``; both ``None`` means the router decides."""
    name = (name or "auto").strip()
    if name in ("auto", "crossvet", "crossvet/auto"):
        return None, None
    if name.startswith(PREFIX):
        slot = name[len(PREFIX):]
        if slot not in SLOTS:
            raise ValueError(f"unknown slot {slot!r}; slots are {', '.join(SLOTS)}")
        return None, slot
    return name, None


def thread_for(messages: list[dict[str, Any]], header: str | None) -> str:
    """Return a stable thread id for a client conversation: the header if sent, else a hash of its first user message."""
    if header:
        return header[:64]
    first = next((user_text(m) for m in messages if m.get("role") == "user"), "")
    return "c" + hashlib.sha256(first.encode()).hexdigest()[:11]


def wants_relay(body: dict[str, Any]) -> bool:
    """Whether a request carries tools or tool results, so it must be passed through whole."""
    if body.get("tools") or body.get("functions"):
        return True
    return any(m.get("role") == "tool" or m.get("tool_calls") for m in body.get("messages") or [])


def info(answer: Answer) -> dict[str, Any]:
    """Return what the response adds under ``crossvet``: who answered, why, and the cost."""
    return {"model": answer.model, "served_by": answer.served_by, "slot": answer.decision.slot, "router": answer.decision.router,
            "kind": answer.decision.task.kind, "why": answer.decision.explain(), "cost": answer.cost,
            "thread": answer.thread, "turn": answer.turn_id,
            "attempts": [{"model": a.model, "ok": a.ok, "problem": a.problem} for a in answer.attempts]}


def command(hub: Hub, text: str, thread: str, app: str) -> tuple[str, Answer | None] | None:
    """Handle a chat command typed as the whole message; ``None`` when the text is not one."""
    words = text.strip().split()
    if not words or not words[0].startswith("/"):
        return None
    name = words[0].lower()
    if name == "/why":
        last = [t for t in hub.memory.turns(thread, 50) if t.role == "assistant"]
        return ((f"{last[-1].model}: {last[-1].meta.get('why', '(no reason saved)')}" if last
                 else "Nothing has been answered in this conversation yet."), None)
    if name in ("/good", "/bad"):
        hub.feedback(name == "/good", thread=thread, comment=" ".join(words[1:]), source=app)
        return "Thanks: rated " + ("good." if name == "/good" else "bad."), None
    if name == "/retry":
        answer = hub.retry(thread, stronger=len(words) > 1 and words[1].lower() == "stronger", author=app)
        return answer.text, answer
    return None


def create_app(hub: Hub | None = None, token: str | None = None):
    """Build the Starlette app."""
    from starlette.applications import Starlette
    from starlette.concurrency import run_in_threadpool
    from starlette.requests import Request
    from starlette.responses import HTMLResponse, JSONResponse, StreamingResponse
    from starlette.routing import Route

    hub = hub or Hub()
    token = os.environ.get("CROSSVET_CHAT_TOKEN", "") if token is None else token

    def allowed(request: Request) -> bool:
        if not token:
            return True
        sent = request.headers.get("authorization", "").removeprefix("Bearer ").strip() or request.query_params.get("token", "")
        return hmac.compare_digest(sent.encode(), token.encode())

    def error(status: int, message: str, kind: str = "invalid_request_error") -> JSONResponse:
        return JSONResponse({"error": {"message": message, "type": kind}}, status_code=status)

    def denied() -> JSONResponse:
        return error(401, "missing or wrong token", "authentication_error")

    async def health(_: Request) -> JSONResponse:
        return JSONResponse({"status": "ok", "version": __version__})

    async def models(request: Request) -> JSONResponse:
        if not allowed(request):
            return denied()
        names = ["auto", *(f"{PREFIX}{s}" for s in SLOTS if hub.config.slots.get(s)), *hub.config.all_models()]
        return JSONResponse({"object": "list", "data": [{"id": n, "object": "model", "owned_by": "crossvet"} for n in names]})

    async def turns(request: Request) -> JSONResponse:
        if not allowed(request):
            return denied()
        limit = min(int(request.query_params.get("limit", "60") or 60), 200)
        rows = [{"id": t.id, "thread": t.thread, "ts": t.ts, "author": t.author, "role": t.role, "model": t.model,
                 "content": t.content, "cost": t.cost, "meta": t.meta} for t in hub.memory.recent(limit)]
        return JSONResponse({"turns": rows, "spent_today": hub.memory.spent_today()})

    async def feedback(request: Request) -> JSONResponse:
        if not allowed(request):
            return denied()
        try:
            body = await request.json()
            value = body.get("value", body.get("rating"))
            good = value in ("good", "up", True, 1, 1.0) or (isinstance(value, (int, float)) and value >= 0.5)
            turn = int(body["turn"]) if body.get("turn") is not None else None
            if turn is None and not body.get("thread"):
                raise ValueError("send turn (an answer's id) or thread")
            rating = await run_in_threadpool(hub.feedback, bool(good), thread=body.get("thread"), turn_id=turn,
                                             comment=str(body.get("comment", ""))[:2000], source=request.headers.get("x-crossvet-app", "api")[:40])
        except (KeyError, TypeError, ValueError) as exc:
            return error(400, f"bad request: {exc}")
        return JSONResponse({"rating": rating, "good": bool(good)})

    async def viewer(request: Request) -> HTMLResponse | JSONResponse:
        if not allowed(request):
            return error(401, "open this page as /?token=<CROSSVET_CHAT_TOKEN>", "authentication_error")
        return HTMLResponse(VIEWER, headers={"Content-Security-Policy": "default-src 'self' 'unsafe-inline'", "X-Frame-Options": "DENY"})

    def completion(text: str, model: str, extra: dict[str, Any], usage: dict[str, int], stream: bool,
                   tool_calls: list[dict[str, Any]] | None = None, finish: str = "stop"):
        created = int(time.time())
        cid = "chatcmpl-" + hashlib.sha256(f"{time.time()}{text}".encode()).hexdigest()[:24]
        message: dict[str, Any] = {"role": "assistant", "content": (text or None) if tool_calls else text}
        if tool_calls:
            message["tool_calls"] = tool_calls
        if stream:
            def events():
                delta: dict[str, Any] = {"role": "assistant", "content": text or ""}
                if tool_calls:
                    delta["tool_calls"] = [{"index": i, **c} for i, c in enumerate(tool_calls)]
                first = {"id": cid, "object": "chat.completion.chunk", "created": created, "model": model,
                         "choices": [{"index": 0, "delta": delta, "finish_reason": None}]}
                last = {"id": cid, "object": "chat.completion.chunk", "created": created, "model": model,
                        "choices": [{"index": 0, "delta": {}, "finish_reason": finish}], "usage": usage, "crossvet": extra}
                yield f"data: {json.dumps(first)}\n\n"
                yield f"data: {json.dumps(last)}\n\n"
                yield "data: [DONE]\n\n"
            return StreamingResponse(events(), media_type="text/event-stream")
        return JSONResponse({"id": cid, "object": "chat.completion", "created": created, "model": model,
                             "choices": [{"index": 0, "message": message, "finish_reason": finish}],
                             "usage": usage, "crossvet": extra})

    async def chat(request: Request):
        if not allowed(request):
            return denied()
        try:
            body = await request.json()
            raw_messages = list(body["messages"])
            users = [m for m in raw_messages if m.get("role") == "user"]
            prompt = user_text(users[-1])
            model, slot = resolve_model(str(body.get("model", "auto")))
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            return error(400, f"bad request: {exc}")
        thread = thread_for(raw_messages, request.headers.get("x-crossvet-thread"))
        app = request.headers.get("x-crossvet-app", "api")[:40]
        stream = bool(body.get("stream"))
        router = request.headers.get("x-crossvet-router") or None
        try:
            if wants_relay(body):
                raw, answer = await run_in_threadpool(hub.relay, body, thread=thread, author=app, model=model, slot=slot,
                                                   router=router)
                choice = (raw.get("choices") or [{}])[0]
                usage = raw.get("usage") or {}
                return completion(answer.text, answer.model, info(answer),
                                  {k: usage.get(k, 0) for k in ("prompt_tokens", "completion_tokens", "total_tokens")},
                                  stream, answer.tool_calls, str(choice.get("finish_reason") or "stop"))
            handled = await run_in_threadpool(command, hub, prompt, thread, app)
            if handled is not None:
                text, answer = handled
                return completion(text, answer.model if answer else "crossvet", info(answer) if answer else {"command": prompt.split()[0]},
                                  {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}, stream)
            messages = [{"role": m.get("role"), "content": user_text(m)} for m in raw_messages]
            last_user = max(i for i, m in enumerate(messages) if m["role"] == "user")
            history = [m for m in messages[:last_user] if m["role"] in ("user", "assistant")]
            system = "\n\n".join(m["content"] for m in messages if m["role"] == "system") or None
            answer = await run_in_threadpool(hub.ask, prompt, thread=thread, model=model, slot=slot, author=app,
                                             system=system, history=history, router=router)
        except BudgetExceeded as exc:
            return error(429, str(exc), "budget_exceeded")
        except NoModel as exc:
            return error(503, str(exc), "no_model")
        except (ProviderError, ValueError) as exc:
            return error(502, str(exc), "upstream_error")
        usage = {"prompt_tokens": answer.input_tokens, "completion_tokens": answer.output_tokens,
                 "total_tokens": answer.input_tokens + answer.output_tokens}
        return completion(answer.text, answer.model, info(answer), usage, stream)

    return Starlette(routes=[
        Route("/health", health), Route("/v1/models", models), Route("/v1/chat/completions", chat, methods=["POST"]),
        Route("/api/turns", turns), Route("/api/feedback", feedback, methods=["POST"]), Route("/", viewer)])


def serve(host: str = "127.0.0.1", port: int = 8787) -> int:
    """Run the server; refuse a non-local address without a token."""
    import sys

    token = os.environ.get("CROSSVET_CHAT_TOKEN", "")
    if host not in LOCAL_HOSTS and not token:
        print("refusing to listen on a non-local address without CROSSVET_CHAT_TOKEN set", file=sys.stderr)
        return 2
    import uvicorn

    print(f"OpenAI-compatible API: http://{host}:{port}/v1 (model: auto)   activity: http://{host}:{port}/", file=sys.stderr)
    uvicorn.run(create_app(), host=host, port=port, log_level="warning")
    return 0
