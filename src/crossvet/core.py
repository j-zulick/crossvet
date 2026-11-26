"""The one place every request goes through: name the model, guard the call, log the turn.

The terminal chat, the OpenAI-compatible server and the MCP server all call :class:`Crossvet`.
The request names its model (or gets ``default_model``). Only a request that names ``auto``, a slot
(``crossvet/strong``) or a goal (``crossvet/cheapest``) lets Crossvet choose (routing.py); then the
decision is recorded and the next model on the ladder is tried after an error, an empty answer or
invalid JSON (at most ``[router] max_steps`` times). The guards are code:

- a daily spend cap and a per-call worst-case estimate (``[limits]``), checked before the call;
- a provider that refuses your key, credit or billing is not called again until restart;
- one time limit and one output limit for every call.

A failed call to a model you named raises an error that names the model, so you can pick another:
nothing is retried and nothing switches models behind your back.
"""

from __future__ import annotations

import itertools
import json
import random
import threading
import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from typing import Any

from crossvet import providers, relay, routing
from crossvet.bench import strip_fences
from crossvet.config import Config, load
from crossvet.lab import Lab
from crossvet.providers import AccountError, ProviderError, Reply, text_of
from crossvet.store import Store, new_thread

CHARS_PER_TOKEN = 4  # a rough count, used only for the per-call cap
SCORE_CACHE_SECONDS = 300  # how long routing reuses the leaderboard


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
    decision: dict[str, Any] | None = None  # set when Crossvet chose the model (auto, a slot or a goal)

    def footer(self) -> str:
        """One line: model, tokens, cost and time (and the slot, when Crossvet chose)."""
        cost = "price unknown" if self.cost is None else f"${self.cost:.4f}"
        note = " · stopped at the output limit" if self.truncated else " · the answer was cut off" if self.stop == "error" else ""
        chose = f" · auto: {self.decision['slot']} slot, /why explains" if self.decision else ""
        return f"{self.model} · {self.input_tokens} in / {self.output_tokens} out · {cost} · {self.seconds:.1f} s{note}{chose}"


Streamer = Callable[[str, list[dict[str, Any]], int], Iterator["str | Reply"]]
Relayer = Callable[[str, dict[str, Any], dict[str, Any]], tuple[dict[str, Any], Reply]]
RelayStreamer = Callable[[str, dict[str, Any], dict[str, Any]], Iterator["dict[str, Any] | Reply"]]


def estimate_tokens(text: str) -> int:
    """Rough token count for ``text``."""
    return len(text) // CHARS_PER_TOKEN + 1


def problem(answer: Answer, wants_json: bool) -> str:
    """Return what is wrong with an answer, in words ("" when nothing is): decides escalation, in code."""
    if not answer.text.strip() and not answer.tool_calls:
        return "empty answer"
    if wants_json and not answer.tool_calls:
        try:
            json.loads(strip_fences(answer.text))
        except ValueError:
            return "invalid JSON"
    if answer.truncated:
        return "cut off at the output limit"
    return ""


def last_user_text(messages: list[dict[str, Any]]) -> str:
    """Return the text of the latest user message ("" when there is none)."""
    return next((text_of(m.get("content")) for m in reversed(messages) if m.get("role") == "user"), "")


class Crossvet:
    """Ask a named model; guard the call; log the turn."""

    def __init__(self, config: Config | None = None, store: Store | None = None, *,  # noqa: D107
                 streamer: Streamer | None = None, relayer: Relayer | None = None,
                 relay_streamer: RelayStreamer | None = None, lab: Lab | None = None) -> None:
        self.config = config or load()
        providers.set_timeout(self.config.timeout_seconds)
        self.store = store or Store(self.config.store_path())
        self.lab = lab or Lab(":memory:" if self.store.path == ":memory:" else self.config.lab_path(self.store.path))
        self.streamer: Streamer = streamer or (lambda m, msgs, n: providers.stream(m, msgs, n))
        self.relayer: Relayer = relayer or (lambda m, body, state: relay.send(m, body, state))
        self.relay_streamer: RelayStreamer = relay_streamer or (lambda m, body, state: relay.send_stream(m, body, state))
        self.refused: set[str] = set()  # providers that refused the account in this process
        self.rng = random.Random()  # exploration under [router] use = "scores"; tests seed it
        self._score_cache: tuple[float, dict[str, Any], bool] | None = None
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

    # --- choosing (only when the request asks for it) ---

    def decide(self, name: str | None, messages: list[dict[str, Any]], author: str = "") -> routing.Decision:
        """Choose a model for a request that named auto, a slot or a goal (nothing is called)."""
        board, trusted = self._scores() if self.config.router_use == "scores" else (None, True)
        return routing.decide(self.config, messages, name or "auto", pinned=self.lab.pinned(), store=self.store, author=author,
                              board=board, trusted=trusted, rng=self.rng)

    def _scores(self) -> tuple[dict[str, Any], bool]:
        """Return the leaderboard and whether the judge is trusted, kept for five minutes."""
        from crossvet import score

        now = time.monotonic()
        if self._score_cache is None or now - self._score_cache[0] > SCORE_CACHE_SECONDS:
            self._score_cache = (now, score.leaderboard(self, 30), score.calibration(self)["trusted"])
        return self._score_cache[1], self._score_cache[2]

    def label(self, name: str | None) -> str:
        """Return the model a name means, or the name itself when Crossvet will choose."""
        return (name or "auto") if routing.is_auto(name) else self.config.resolve(name)

    def _tries(self, decision: routing.Decision) -> list[str]:
        return list(decision.ladder)  # routing.decide already keeps only the models escalation may try

    def _auto_stream(self, name: str, messages: list[dict[str, Any]], thread: str, app: str) -> Iterator[str | Answer]:
        decision = self.decide(name, messages)
        tries, steps = self._tries(decision), []
        for i, model in enumerate(tries):
            last = i == len(tries) - 1
            held: list[str] = []  # JSON answers are held back until they are checked
            started, answer = False, None
            try:
                for item in self.ask_stream(model, messages, thread=thread, app=app):
                    if isinstance(item, Answer):
                        answer = item
                    elif decision.wants_json:
                        held.append(item)
                    else:
                        started = True
                        yield item
            except ProviderError as exc:  # an account refusal is one too: the next vendor may still answer
                steps.append({"model": model, "outcome": f"error: {str(exc)[:200]}"})
                if started or last:
                    raise
                continue
            assert answer is not None  # noqa: S101 - ask_stream always ends with an Answer
            wrong = problem(answer, decision.wants_json)
            if wrong and not started and not last and wrong != "cut off at the output limit":
                steps.append({"model": model, "outcome": wrong, "turn": answer.turn_id})
                continue
            yield from held
            steps.append({"model": model, "outcome": wrong or "ok", "turn": answer.turn_id})
            answer.decision = {**decision.as_dict(), "model": model, "steps": steps}
            self.lab.record_decision(answer.turn_id, thread, name, {**decision.as_dict(), "model": model}, steps)
            yield answer
            return

    # --- asking ---

    def ask_stream(self, model_name: str | None, messages: list[dict[str, Any]], *, thread: str | None = None,
                   app: str = "api") -> Iterator[str | Answer]:
        """Stream the answer: each piece of text, then the logged :class:`Answer`.

        A named model answers, or Crossvet chooses when the name is auto, a slot or a goal.
        """
        if routing.is_auto(model_name):
            yield from self._auto_stream(str(model_name), messages, thread or new_thread(), app)
            return
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

    def _candidates(self, model_name: str | None, body: dict[str, Any]) -> tuple[list[str | None], routing.Decision | None]:
        if not routing.is_auto(model_name):
            return [model_name], None
        decision = self.decide(model_name, list(body.get("messages") or []))
        return list(self._tries(decision)), decision

    def _note(self, answer: Answer, decision: routing.Decision | None, name: str | None, steps: list[dict[str, Any]]) -> Answer:
        if decision is not None:
            steps.append({"model": answer.model, "outcome": "ok", "turn": answer.turn_id})
            answer.decision = {**decision.as_dict(), "model": answer.model, "steps": steps}
            self.lab.record_decision(answer.turn_id, answer.thread, str(name), {**decision.as_dict(), "model": answer.model}, steps)
        return answer

    def relay(self, model_name: str | None, body: dict[str, Any], *, thread: str | None = None,
              app: str = "api") -> tuple[dict[str, Any], Answer]:
        """Pass an agent's whole request (tools and tool results included) to the model; log the turn.

        With auto, a slot or a goal, an error moves to the next model on the ladder.
        """
        candidates, decision = self._candidates(model_name, body)
        steps: list[dict[str, Any]] = []
        for i, name in enumerate(candidates):
            model, sent, state = self._relay_prepare(name, body)
            try:
                raw, reply = self.relayer(model, sent, state)
            except ProviderError as exc:
                if isinstance(exc, AccountError):
                    self._refusal(model)
                steps.append({"model": model, "outcome": f"error: {str(exc)[:200]}"})
                if i == len(candidates) - 1:
                    raise
                continue
            answer = self._log(model, last_user_text(sent["messages"]), reply, thread or new_thread(), app)
            return raw, self._note(answer, decision, model_name, steps)
        raise ProviderError("no model answered")  # pragma: no cover - the loop returns or raises

    def relay_stream(self, model_name: str | None, body: dict[str, Any], *, thread: str | None = None,
                     app: str = "api") -> Iterator[dict[str, Any] | Answer]:
        """Stream an agent's request: chat-completions deltas as they arrive, then the logged :class:`Answer`.

        With auto, a slot or a goal, an error before anything was streamed moves to the next model.
        """
        candidates, decision = self._candidates(model_name, body)
        steps: list[dict[str, Any]] = []
        for i, name in enumerate(candidates):
            stream = self._relay_stream_one(name, body, thread=thread, app=app)
            try:
                first = next(stream)
            except ProviderError as exc:
                steps.append({"model": self.label(name), "outcome": f"error: {str(exc)[:200]}"})
                if i == len(candidates) - 1:
                    raise
                continue
            for item in itertools.chain([first], stream):
                if isinstance(item, Answer):
                    item = self._note(item, decision, model_name, steps)
                yield item
            return

    def _relay_stream_one(self, model_name: str | None, body: dict[str, Any], *, thread: str | None,
                          app: str) -> Iterator[dict[str, Any] | Answer]:
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
