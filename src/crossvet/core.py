"""The one place every request goes through: name the model, guard the call, log the turn.

The terminal chat, the OpenAI-compatible server and the MCP server all call :class:`Crossvet`.
It never chooses a model: the request names one (or gets ``default_model``). The guards are code:

- a daily spend cap and a per-call worst-case estimate (``[limits]``), checked before the call;
- a provider that refuses your key, credit or billing is not called again until restart;
- one time limit and one output limit for every call.

A failed call raises an error that names the model, so you can pick another. Nothing is retried
and nothing switches models behind your back.
"""

from __future__ import annotations

import json
import threading
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from typing import Any

from crossvet import providers, relay
from crossvet.config import Config, load
from crossvet.providers import AccountError, Reply, text_of
from crossvet.store import Store, new_thread

CHARS_PER_TOKEN = 4  # a rough count, used only for the per-call cap


class BudgetExceeded(RuntimeError):
    """A spend cap stopped the call before it was made."""


@dataclass
class Answer:
    """One model's answer, as logged."""

    text: str
    model: str
    thread: str
    turn_id: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cost: float | None = None
    seconds: float = 0.0
    truncated: bool = False
    stop: str = ""
    served_by: str = ""
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    dropped: list[str] = field(default_factory=list)

    def footer(self) -> str:
        """One line: model, tokens, cost and time."""
        cost = "price unknown" if self.cost is None else f"${self.cost:.4f}"
        note = " · stopped at the output limit" if self.truncated else " · the answer was cut off" if self.stop == "error" else ""
        return f"{self.model} · {self.input_tokens} in / {self.output_tokens} out · {cost} · {self.seconds:.1f} s{note}"


Streamer = Callable[[str, list[dict[str, Any]], int], Iterator["str | Reply"]]
Relayer = Callable[[str, dict[str, Any], dict[str, Any]], tuple[dict[str, Any], Reply]]
RelayStreamer = Callable[[str, dict[str, Any], dict[str, Any]], Iterator["dict[str, Any] | Reply"]]


def estimate_tokens(text: str) -> int:
    """Rough token count for ``text``."""
    return len(text) // CHARS_PER_TOKEN + 1


def last_user_text(messages: list[dict[str, Any]]) -> str:
    """Return the text of the latest user message ("" when there is none)."""
    return next((text_of(m.get("content")) for m in reversed(messages) if m.get("role") == "user"), "")


class Crossvet:
    """Ask a named model; guard the call; log the turn."""

    def __init__(self, config: Config | None = None, store: Store | None = None, *,  # noqa: D107
                 streamer: Streamer | None = None, relayer: Relayer | None = None,
                 relay_streamer: RelayStreamer | None = None) -> None:
        self.config = config or load()
        providers.set_timeout(self.config.timeout_seconds)
        self.store = store or Store(self.config.store_path())
        self.streamer: Streamer = streamer or (lambda m, msgs, n: providers.stream(m, msgs, n))
        self.relayer: Relayer = relayer or (lambda m, body, state: relay.send(m, body, state))
        self.relay_streamer: RelayStreamer = relay_streamer or (lambda m, body, state: relay.send_stream(m, body, state))
        self.refused: set[str] = set()  # providers that refused the account in this process
        self.lock = threading.Lock()

    # --- guards ---

    def check(self, model: str, prompt_text: str) -> None:
        """Raise before the call when the provider refused the account earlier or a spend cap would be passed."""
        provider = providers.split(model)[0]
        if provider in self.refused:
            raise AccountError(f"{provider} refused your key, credit or billing earlier in this run, so {model} is not "
                               "called again; fix it with the provider and restart Crossvet, or pick another model")
        cfg = self.config
        if cfg.max_usd_per_day > 0:
            spent = self.store.spent_today()
            if spent >= cfg.max_usd_per_day:
                raise BudgetExceeded(f"the daily cap is reached: ${spent:.2f} of ${cfg.max_usd_per_day:.2f} "
                                     "([limits] max_usd_per_day)")
        if cfg.max_usd_per_call > 0:
            worst = cfg.cost(model, estimate_tokens(prompt_text), cfg.max_output_tokens)
            if worst is not None and worst > cfg.max_usd_per_call:
                raise BudgetExceeded(f"{model} could cost up to ${worst:.2f} for this request, above the "
                                     f"${cfg.max_usd_per_call:.2f} per-call cap ([limits] max_usd_per_call)")

    def _refusal(self, model: str) -> None:
        self.refused.add(providers.split(model)[0])

    # --- asking ---

    def ask_stream(self, model_name: str | None, messages: list[dict[str, Any]], *, thread: str | None = None,
                   app: str = "api") -> Iterator[str | Answer]:
        """Stream the named model's answer: each piece of text, then the logged :class:`Answer`."""
        model = self.config.resolve(model_name)
        self.check(model, "".join(text_of(m.get("content")) for m in messages))
        thread = thread or new_thread()
        reply: Reply | None = None
        try:
            for item in self.streamer(model, messages, self.config.max_output_tokens):
                if isinstance(item, Reply):
                    reply = item
                else:
                    yield item
        except AccountError:
            self._refusal(model)
            raise
        if reply is None:
            raise providers.ProviderError(f"{model} returned no answer")
        yield self._log(model, last_user_text(messages), reply, thread, app)

    def ask(self, model_name: str | None, messages: list[dict[str, Any]], *, thread: str | None = None,
            app: str = "api") -> Answer:
        """Ask the named model and return the whole :class:`Answer`."""
        answer = None
        for item in self.ask_stream(model_name, messages, thread=thread, app=app):
            if isinstance(item, Answer):
                answer = item
        assert answer is not None  # noqa: S101 - ask_stream always ends with an Answer
        return answer

    def _relay_prepare(self, model_name: str | None, body: dict[str, Any]) -> tuple[str, dict[str, Any], dict[str, Any]]:
        """Resolve, guard, set the output limit, and find the kept reasoning for the tool results in the request."""
        model = self.config.resolve(model_name)
        messages = list(body.get("messages") or [])
        self.check(model, json.dumps(messages) + json.dumps(body.get("tools") or []))
        sent = dict(body)
        if "max_tokens" not in sent and "max_completion_tokens" not in sent:
            sent["max_tokens"] = self.config.max_output_tokens
        call_ids = [str(c.get("id")) for m in messages for c in (m.get("tool_calls") or []) if c.get("id")]
        with self.lock:
            state = self.store.load_state(model, call_ids)
        return model, sent, state

    def relay(self, model_name: str | None, body: dict[str, Any], *, thread: str | None = None,
              app: str = "api") -> tuple[dict[str, Any], Answer]:
        """Pass an agent's whole request (tools and tool results included) to the named model; log the turn."""
        model, sent, state = self._relay_prepare(model_name, body)
        try:
            raw, reply = self.relayer(model, sent, state)
        except AccountError:
            self._refusal(model)
            raise
        return raw, self._log(model, last_user_text(sent["messages"]), reply, thread or new_thread(), app)

    def relay_stream(self, model_name: str | None, body: dict[str, Any], *, thread: str | None = None,
                     app: str = "api") -> Iterator[dict[str, Any] | Answer]:
        """Stream an agent's request: chat-completions deltas as they arrive, then the logged :class:`Answer`."""
        model, sent, state = self._relay_prepare(model_name, body)
        reply: Reply | None = None
        try:
            for item in self.relay_streamer(model, sent, state):
                if isinstance(item, Reply):
                    reply = item
                else:
                    yield item
        except AccountError:
            self._refusal(model)
            raise
        if reply is None:
            raise providers.ProviderError(f"{model} returned no answer")
        yield self._log(model, last_user_text(sent["messages"]), reply, thread or new_thread(), app)

    # --- logging ---

    def _log(self, model: str, question: str, reply: Reply, thread: str, app: str) -> Answer:
        cost = reply.cost if reply.cost is not None else self.config.cost(model, reply.input_tokens, reply.output_tokens)
        answer = Answer(text=reply.text, model=model, thread=thread, input_tokens=reply.input_tokens,
                        output_tokens=reply.output_tokens, cost=cost, seconds=reply.seconds, truncated=reply.truncated,
                        stop=reply.stop, served_by=reply.served_by, tool_calls=reply.tool_calls, dropped=reply.dropped)
        shown = reply.text or ("(tool calls: " + ", ".join(str((c.get("function") or {}).get("name", "?"))
                                                           for c in reply.tool_calls) + ")" if reply.tool_calls else "")
        meta = {"input_tokens": reply.input_tokens, "output_tokens": reply.output_tokens, "seconds": reply.seconds,
                "served_by": reply.served_by, "stop": reply.stop}
        if reply.dropped:
            meta["dropped"] = reply.dropped
        with self.lock:
            if reply.state:
                self.store.save_state(model, reply.state)
            self.store.add_turn(thread, app, "user", question)
            answer.turn_id = self.store.add_turn(thread, app, "assistant", shown, model=model, cost=cost, meta=meta)
        return answer

    # --- reading ---

    def models(self) -> list[dict[str, Any]]:
        """Return the model menu: each model, its short names, whether its key is set, its price, and which is the default."""
        default = ""
        try:
            default = self.config.resolve(None)
        except ValueError:
            pass
        rows = []
        for model in self.config.menu():
            price = self.config.price(model)
            rows.append({"model": model, "names": sorted(n for n, m in self.config.names.items() if m == model),
                         "ready": providers.available(providers.split(model)[0]), "default": model == default,
                         "price": price})
        return rows

    def cost_text(self, *, since: float = 0.0, thread: str | None = None, title: str = "Spend") -> str:
        """Spend per model as plain text."""
        rows = self.store.spending(since=since, thread=thread)
        if not rows:
            return f"{title}: nothing yet."
        lines = [f"{title}:"]
        for model, row in rows.items():
            unpriced = f" ({int(row['unpriced'])} without a price)" if row["unpriced"] else ""
            count = int(row["answers"])
            lines.append(f"  {model:<34} {count:>4} answer{'' if count == 1 else 's'}  ${row['usd']:.4f}{unpriced}")
        total = sum(r["usd"] for r in rows.values())
        lines.append(f"  {'total':<34} {'':>12} ${total:.4f}")
        return "\n".join(lines)

    def models_text(self) -> str:
        """Return the model menu as plain text."""
        lines = []
        for row in self.models():
            price = f"${row['price'][0]:g} / ${row['price'][1]:g} per M tokens" if row["price"] else "price not set"
            names = f" ({', '.join(row['names'])})" if row["names"] else ""
            flags = (" [default]" if row["default"] else "") + ("" if row["ready"] else " [no key]")
            lines.append(f"  {row['model']}{names}  {price}{flags}")
        return "Models (any provider:model works too):\n" + "\n".join(lines) if lines else \
            "No models yet: add an API key (see .env.example), then `crossvet models`."
