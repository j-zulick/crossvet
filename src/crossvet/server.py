"""An OpenAI-compatible server: point Hermes (or any OpenAI-style chat app) at it and pick a model.

    base URL   http://127.0.0.1:8787/v1
    model      any provider:model, a short name (opus, sol...), or "default"

``GET /v1/models`` lists your models, so the app's model menu shows them. Which model answers is
decided by the request, never by Crossvet:

1. the latest ``/model NAME`` typed in the conversation, if any;
2. else the request's ``model`` field;
3. ``default`` (or ``crossvet``) means your ``default_model``.

Commands typed as the whole message (no model is called, and they are left out of what models see):

    /model NAME   use NAME for the rest of this conversation      /models   list your models
    /model        show the model in use                           /cost     spend in this conversation and today
    /help         this list

Agents keep their tools: a request with ``tools`` or tool results is passed through to the named
model (``relay.py``), streamed when the app asks for a stream.

Security: it listens on this computer only by default. Set ``CROSSVET_TOKEN`` to require
``Authorization: Bearer <token>``; any other address needs a token of at least 16 characters.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import itertools
import json
import os
import sys
import time
from collections.abc import Iterator
from typing import Any

from crossvet import __version__
from crossvet.core import Answer, BudgetExceeded, Crossvet
from crossvet.providers import AccountError, ProviderError, text_of

LOCAL_HOSTS = ("127.0.0.1", "localhost", "::1")
MIN_TOKEN_CHARS = 16
FAIL_DELAY_SECONDS = 1.0  # pause before answering a wrong or missing token
COMMANDS = ("/model", "/models", "/cost", "/help")
HELP = ("Crossvet commands: /model NAME (use NAME in this conversation), /model (show it), /models (list them), "
        "/cost (spend here and today), /help.")


def is_command(message: dict[str, Any]) -> bool:
    """Whether a user message is one of Crossvet's commands."""
    if message.get("role") != "user":
        return False
    words = text_of(message.get("content")).strip().split()
    return bool(words) and words[0].lower() in COMMANDS


def without_commands(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Drop Crossvet commands and Crossvet's replies to them, so models never see them."""
    kept: list[dict[str, Any]] = []
    skip_reply = False
    for message in messages:
        if is_command(message):
            skip_reply = True
            continue
        if skip_reply and message.get("role") == "assistant":
            skip_reply = False
            continue
        skip_reply = False
        kept.append(message)
    return kept


def chosen_model(messages: list[dict[str, Any]], requested: str) -> str:
    """Return the latest ``/model NAME`` in the conversation, else the request's model field."""
    for message in reversed(messages):
        if is_command(message):
            words = text_of(message.get("content")).split()
            if words[0].lower() == "/model" and len(words) > 1:
                return words[1]
    return requested


def thread_for(messages: list[dict[str, Any]], header: str | None) -> str:
    """Return a stable id for a conversation: the ``x-crossvet-thread`` header, else a hash of its first question."""
    if header:
        return header[:64]
    first = next((text_of(m.get("content")) for m in messages if m.get("role") == "user" and not is_command(m)), "")
    return "c" + hashlib.sha256(first.encode()).hexdigest()[:11]


def wants_relay(body: dict[str, Any]) -> bool:
    """Whether a request carries tools or tool results, so it must be passed through whole."""
    if body.get("tools") or body.get("functions"):
        return True
    return any(m.get("role") == "tool" or m.get("tool_calls") for m in body.get("messages") or [])


def command(cv: Crossvet, messages: list[dict[str, Any]], requested: str, thread: str) -> str:
    """Answer the command in the last message."""
    words = text_of(messages[-1].get("content")).split()
    name = words[0].lower()
    if name == "/model":
        if len(words) > 1:
            return f"Crossvet: {cv.config.resolve(words[1])} answers the rest of this conversation."
        return f"Crossvet: this conversation uses {cv.config.resolve(chosen_model(messages[:-1], requested))}."
    if name == "/models":
        return cv.models_text()
    if name == "/cost":
        midnight = time.mktime(time.localtime()[:3] + (0, 0, 0, 0, 0, -1))
        return cv.cost_text(thread=thread, title="This conversation") + "\n\n" + cv.cost_text(since=midnight, title="Today")
    return HELP


def info(answer: Answer) -> dict[str, Any]:
    """Return what the response adds under ``crossvet``: the model, cost, conversation and turn."""
    extra = {"model": answer.model, "served_by": answer.served_by, "cost": answer.cost, "thread": answer.thread,
             "turn": answer.turn_id}
    if answer.dropped:
        extra["dropped"] = answer.dropped  # request fields the vendor's API had no place for
    return extra


def create_app(cv: Crossvet | None = None, token: str | None = None):
    """Build the Starlette app."""
    from starlette.applications import Starlette
    from starlette.concurrency import run_in_threadpool
    from starlette.requests import Request
    from starlette.responses import JSONResponse, StreamingResponse
    from starlette.routing import Route

    cv = cv or Crossvet()
    token = os.environ.get("CROSSVET_TOKEN", "") if token is None else token

    def allowed(request: Request) -> bool:
        if not token:
            return True
        sent = request.headers.get("authorization", "").removeprefix("Bearer ").strip()
        return hmac.compare_digest(sent.encode(), token.encode())

    def error(status: int, message: str, kind: str = "invalid_request_error") -> JSONResponse:
        return JSONResponse({"error": {"message": message, "type": kind}}, status_code=status)

    async def denied() -> JSONResponse:
        await asyncio.sleep(FAIL_DELAY_SECONDS)  # slows guessing
        return error(401, "missing or wrong token (send Authorization: Bearer <CROSSVET_TOKEN>)", "authentication_error")

    def new_id(seed: str) -> str:
        return "chatcmpl-" + hashlib.sha256(f"{time.time()}{seed}".encode()).hexdigest()[:24]

    async def health(_: Request) -> JSONResponse:
        return JSONResponse({"status": "ok", "version": __version__})

    async def models(request: Request) -> JSONResponse:
        if not allowed(request):
            return await denied()
        ids = ["default", *cv.config.menu(), *cv.config.names]
        return JSONResponse({"object": "list", "data": [{"id": i, "object": "model", "owned_by": "crossvet"} for i in ids]})

    def whole(text: str, model: str, extra: dict[str, Any], usage: dict[str, int], stream: bool,
              tool_calls: list[dict[str, Any]] | None = None, finish: str = "stop"):
        """Return a finished answer as one JSON reply or as a short stream."""
        cid, created = new_id(text), int(time.time())
        if stream:
            def events() -> Iterator[str]:
                delta: dict[str, Any] = {"role": "assistant", "content": text or ""}
                if tool_calls:
                    delta["tool_calls"] = [{"index": i, **c} for i, c in enumerate(tool_calls)]
                for body in ({"choices": [{"index": 0, "delta": delta, "finish_reason": None}]},
                             {"choices": [{"index": 0, "delta": {}, "finish_reason": finish}], "usage": usage, "crossvet": extra}):
                    yield f"data: {json.dumps({'id': cid, 'object': 'chat.completion.chunk', 'created': created, 'model': model, **body})}\n\n"
                yield "data: [DONE]\n\n"
            return StreamingResponse(events(), media_type="text/event-stream")
        message: dict[str, Any] = {"role": "assistant", "content": (text or None) if tool_calls else text}
        if tool_calls:
            message["tool_calls"] = tool_calls
        return JSONResponse({"id": cid, "object": "chat.completion", "created": created, "model": model,
                             "choices": [{"index": 0, "message": message, "finish_reason": finish}],
                             "usage": usage, "crossvet": extra})

    def streamed(first: str | Answer | None, rest: Iterator[str | Answer], model: str) -> Iterator[str]:
        """Each piece of text as its own chunk, then a closing chunk with usage and cost."""
        cid, created = new_id(model), int(time.time())

        def chunk(delta: dict[str, Any], finish: str | None = None, **more: Any) -> str:
            body = {"id": cid, "object": "chat.completion.chunk", "created": created, "model": model,
                    "choices": [{"index": 0, "delta": delta, "finish_reason": finish}], **more}
            return f"data: {json.dumps(body)}\n\n"

        yield chunk({"role": "assistant", "content": ""})
        try:
            for item in itertools.chain([first] if first is not None else [], rest):
                if isinstance(item, Answer):
                    yield chunk({}, "length" if item.truncated else "stop", usage=usage_of(item), crossvet=info(item))
                else:
                    yield chunk({"content": item})
        except Exception as exc:  # noqa: BLE001 - the response has started; report the failure in the stream
            yield chunk({"content": f"\n\n[crossvet: {model} stopped: {str(exc)[:200]}]"}, "stop")
        yield "data: [DONE]\n\n"

    def relayed(first: dict[str, Any] | Answer | None, rest: Iterator[dict[str, Any] | Answer], model: str) -> Iterator[str]:
        """Stream an agent's reply: each delta as its own chunk, then usage and cost."""
        cid, created = new_id(model), int(time.time())
        finished = False

        def chunk(choices: list[dict[str, Any]], **more: Any) -> str:
            body = {"id": cid, "object": "chat.completion.chunk", "created": created, "model": model, "choices": choices, **more}
            return f"data: {json.dumps(body)}\n\n"

        try:
            for item in itertools.chain([first] if first is not None else [], rest):
                if isinstance(item, Answer):
                    if not finished:
                        yield chunk([{"index": 0, "delta": {}, "finish_reason": "error" if item.stop == "error" else "stop"}])
                    yield chunk([], usage=usage_of(item), crossvet=info(item))
                else:
                    finished = finished or bool(item.get("finish_reason"))
                    yield chunk([{"index": 0, "delta": item.get("delta") or {}, "finish_reason": item.get("finish_reason")}])
        except Exception as exc:  # noqa: BLE001 - the response has started; report the failure in the stream
            yield chunk([{"index": 0, "delta": {"content": f"\n\n[crossvet: {model} stopped: {str(exc)[:200]}]"},
                          "finish_reason": "stop"}])
        yield "data: [DONE]\n\n"

    def usage_of(answer: Answer) -> dict[str, int]:
        return {"prompt_tokens": answer.input_tokens, "completion_tokens": answer.output_tokens,
                "total_tokens": answer.input_tokens + answer.output_tokens}

    async def chat(request: Request):
        if not allowed(request):
            return await denied()
        limit = cv.config.max_request_bytes
        declared = request.headers.get("content-length", "")
        too_large = error(413, f"the request is larger than [limits] max_request_bytes ({limit})", "request_too_large")
        if declared.isdigit() and int(declared) > limit:
            return too_large
        raw_body = await request.body()
        if len(raw_body) > limit:
            return too_large
        try:
            body = json.loads(raw_body)
            messages = list(body["messages"])
            if not any(m.get("role") == "user" for m in messages):
                raise ValueError("no user message")
        except (KeyError, TypeError, ValueError) as exc:
            return error(400, f"bad request: {exc}")
        requested = str(body.get("model") or "default")
        thread = thread_for(messages, request.headers.get("x-crossvet-thread"))
        app = request.headers.get("x-crossvet-app", "api")[:40]
        stream = bool(body.get("stream"))
        model_name = chosen_model(messages, requested)
        try:
            if is_command(messages[-1]):
                text = await run_in_threadpool(command, cv, messages, requested, thread)
                zero = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
                return whole(text, "crossvet", {"command": text_of(messages[-1]["content"]).split()[0]}, zero, stream)
            sent = without_commands(messages)
            if wants_relay(body) and stream:
                deltas = cv.relay_stream(model_name, {**body, "messages": sent}, thread=thread, app=app)
                first = await run_in_threadpool(next, deltas, None)  # errors before any output become HTTP errors
                return StreamingResponse(relayed(first, deltas, cv.config.resolve(model_name)), media_type="text/event-stream")
            if wants_relay(body):
                raw, answer = await run_in_threadpool(cv.relay, model_name, {**body, "messages": sent}, thread=thread, app=app)
                choice = (raw.get("choices") or [{}])[0]
                return whole(answer.text, answer.model, info(answer), usage_of(answer), stream, answer.tool_calls,
                             str(choice.get("finish_reason") or "stop"))
            if stream:
                pieces = cv.ask_stream(model_name, sent, thread=thread, app=app)
                first = await run_in_threadpool(next, pieces, None)  # errors before any text become HTTP errors
                return StreamingResponse(streamed(first, pieces, cv.config.resolve(model_name)), media_type="text/event-stream")
            answer = await run_in_threadpool(cv.ask, model_name, sent, thread=thread, app=app)
        except BudgetExceeded as exc:
            return error(429, str(exc), "budget_exceeded")
        except AccountError as exc:
            return error(402, str(exc), "account_refused")
        except ValueError as exc:  # an unknown model name
            return error(400, str(exc), "unknown_model")
        except ProviderError as exc:
            return error(502, f"{model_name}: {exc}. Pick another model with /model NAME, or try again.", "upstream_error")
        return whole(answer.text, answer.model, info(answer), usage_of(answer), stream,
                     finish="length" if answer.truncated else "stop")

    return Starlette(routes=[Route("/health", health), Route("/v1/models", models),
                             Route("/v1/chat/completions", chat, methods=["POST"])])


def serve(host: str = "127.0.0.1", port: int = 8787, cv: Crossvet | None = None) -> int:
    """Run the server; refuse a non-local address without a token."""
    token = os.environ.get("CROSSVET_TOKEN", "")
    if host not in LOCAL_HOSTS and len(token) < MIN_TOKEN_CHARS:
        print(f"refusing to listen on {host} without CROSSVET_TOKEN of at least {MIN_TOKEN_CHARS} characters "
              "(`openssl rand -base64 24` makes one)", file=sys.stderr)
        return 2
    import uvicorn

    print(f"Crossvet {__version__}: OpenAI-compatible API at http://{host}:{port}/v1 . Ctrl-C stops it.", file=sys.stderr)
    uvicorn.run(create_app(cv), host=host, port=port, log_level="warning")
    return 0
