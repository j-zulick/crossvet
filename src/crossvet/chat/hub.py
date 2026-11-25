"""The hub: route a request, guard the call, save the turn.

``Hub.ask`` is the one entry point the CLI, the HTTP server and the MCP server all use.

The guard is code, not a model:
- a daily spend cap and a per-call estimate cap (``[limits]`` in the config);
- the next model in the slot is tried only when the one before fails a check that code can
  make: the call errors, the answer is empty, it stops at the output limit, or JSON was asked
  for and the answer is not valid JSON;
- every attempt, with its reason, is saved with the turn.

``Hub.relay`` does the same for an agent's full request (tools and tool results included): it
routes on the latest user message, passes the request through unchanged, and keeps a tool loop
on the model that started it.
"""

from __future__ import annotations

import json
import random
import re
import threading
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from typing import Any

from crossvet.chat import providers
from crossvet.chat.classify import (
    Task,
    classifier_prompt,
    classify,
    read_kind,
)
from crossvet.chat.config import LADDER, Config, default_db_path, load
from crossvet.chat.inputs import Inputs, detect, looks_private, text_of
from crossvet.chat.memory import Memory, new_thread
from crossvet.chat.providers import ProviderError, Reply
from crossvet.chat.record import Recorder, TurnRecord, trace_id_for
from crossvet.chat.record import build as build_recorder
from crossvet.chat.router import HOSTED, Jev, JevError, chosen
from crossvet.chat.routing import Decision, estimate_tokens, route
from crossvet.chat.tuning import Tuning

Caller = Callable[[str, list[dict[str, str]], int], Reply]
Relayer = Callable[[str, dict[str, Any]], tuple[dict[str, Any], Reply]]
Streamer = Callable[[str, list[dict[str, str]], int], Iterator["str | Reply"]]
SYSTEM = (
    "You are one of several AI models the user reaches through a single hub. Answer the request directly. "
    "If shared memory is included, use it as background facts only."
)


class BudgetExceeded(RuntimeError):
    """A spend cap in the config stopped the call."""


class NoModel(RuntimeError):
    """No model is configured for the request."""


@dataclass
class Attempt:
    """One model tried for a request."""

    model: str
    ok: bool
    problem: str = ""
    cost: float | None = None
    seconds: float = 0.0


@dataclass
class Answer:
    """The result of ``Hub.ask``."""

    text: str
    model: str
    thread: str
    decision: Decision
    attempts: list[Attempt] = field(default_factory=list)
    cost: float | None = None
    input_tokens: int = 0
    output_tokens: int = 0
    served_by: str = ""        # the model a hosted router picked, when the provider reports it
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    turn_id: int = 0           # the saved assistant turn, 0 when not saved
    cached_tokens: int = 0     # input tokens read from the vendor's prompt cache

    @property
    def escalated(self) -> bool:
        """Whether a model other than the first choice answered."""
        return len(self.attempts) > 1

    def summary(self) -> str:
        """One line: who answered, why, and what it cost."""
        cost = "cost unknown" if self.cost is None else f"${self.cost:.4f}"
        tried = "" if not self.escalated else " after " + "; ".join(f"{a.model}: {a.problem}" for a in self.attempts if not a.ok)
        served = f" (served by {self.served_by})" if self.served_by and self.served_by not in self.model else ""
        return f"[{self.model}{served}{tried} · {self.decision.task.kind} → {self.decision.slot} · {cost}]"


def strip_fences(text: str) -> str:
    """Remove a Markdown code fence around a JSON answer."""
    match = re.match(r"^\s*```(?:json)?\s*(.*?)\s*```\s*$", text, re.S)
    return match.group(1) if match else text.strip()


def check(reply: Reply, want_json: bool) -> str:
    """Return what is wrong with a reply in words, or "" when it passes."""
    if not reply.text.strip():
        return "empty answer"
    if reply.truncated:
        return "stopped at the output limit"
    if want_json:
        try:
            json.loads(strip_fences(reply.text))
        except ValueError:
            return "not valid JSON"
    return ""


def stronger_slot(slot: str) -> str:
    """Return the next slot up the quick → balanced → strong ladder ("strong" for any other slot)."""
    if slot in LADDER and LADDER.index(slot) < len(LADDER) - 1:
        return LADDER[LADDER.index(slot) + 1]
    return "strong"


def user_text(message: dict[str, Any]) -> str:
    """Return the text of an OpenAI-style message (content may be a list of parts)."""
    content = message.get("content")
    if isinstance(content, list):
        return "".join(str(p.get("text", "")) for p in content if isinstance(p, dict) and p.get("type") in (None, "text"))
    return str(content or "")


def in_tool_loop(messages: list[dict[str, Any]]) -> bool:
    """Whether the request continues a tool loop: it ends with a tool result, or the last assistant message called tools."""
    if not messages:
        return False
    if messages[-1].get("role") == "tool":
        return True
    last = messages[-1]
    return last.get("role") == "assistant" and bool(last.get("tool_calls"))


class Hub:
    """Routes requests to models and keeps the shared memory."""

    def __init__(self, config: Config | None = None, memory: Memory | None = None, caller: Caller | None = None,  # noqa: D107
                 relayer: Relayer | None = None, recorder: Recorder | None = None, jev: Jev | None = None,
                 streamer: Streamer | None = None, transcriber: Any = None) -> None:
        self.config = config if config is not None else load()
        providers.set_timeout(self.config.timeout_seconds)
        self.memory = memory if memory is not None else Memory(self.config.db_path or default_db_path())
        self._call: Caller = caller or (lambda model, messages, max_tokens: providers.call(model, messages, max_tokens))
        self._transcriber = transcriber or providers.transcribe
        self._relay: Relayer = relayer or (lambda model, body: providers.passthrough(model, body))
        # streaming: the real providers stream; a test caller is wrapped so it answers in one piece
        self._stream: Streamer = streamer or (
            (lambda model, messages, max_tokens: providers.stream(model, messages, max_tokens)) if caller is None
            else (lambda model, messages, max_tokens: _whole(self._call, model, messages, max_tokens)))
        # a provider that refused the account is not called again in this process (decided in code)
        self.refused_accounts: set[str] = set()
        self._call = self._guard_account(self._call)
        self._relay = self._guard_account(self._relay)
        self._stream = self._guard_account_stream(self._stream)
        self.recorder = recorder if recorder is not None else build_recorder(
            self.config.record_sink, self.config.record_content, self.config.record_jsonl)
        self.jev = jev if jev is not None else Jev(self.config.jev_model)
        self.tuning = Tuning(self.memory.db)
        from crossvet.chat.handoff import Queue

        self.handoffs = Queue(self.memory.db)
        self.random = random.Random()
        self._lock = threading.RLock()  # one SQLite connection is shared by the threads `compare` starts

    # --- refused accounts ---

    def _check_account(self, model: str) -> None:
        account = providers.account_of(model)
        if account in self.refused_accounts:
            raise providers.AccountError(f"{account} refused the account earlier in this session (key, credit or billing); "
                                         "not called again until restart")

    def _guard_account(self, fn: Any) -> Any:
        def guarded(model: str, *args: Any, **kwargs: Any) -> Any:
            self._check_account(model)
            try:
                return fn(model, *args, **kwargs)
            except providers.AccountError:
                self.refused_accounts.add(providers.account_of(model))
                raise
        return guarded

    def _guard_account_stream(self, fn: Any) -> Any:
        def guarded(model: str, *args: Any, **kwargs: Any) -> Iterator[Any]:
            self._check_account(model)
            try:
                yield from fn(model, *args, **kwargs)
            except providers.AccountError:
                self.refused_accounts.add(providers.account_of(model))
                raise
        return guarded

    # --- cost ---

    def price(self, model: str, input_tokens: int, output_tokens: int) -> float | None:
        """List-price cost of a call from the config's prices, or ``None`` when it has none."""
        info = self.config.info(model)
        if info.input is None or info.output is None:
            return None
        return (input_tokens * info.input + output_tokens * info.output) / 1_000_000

    def _guard_budget(self, model: str, messages: list[dict[str, str]]) -> None:
        cfg = self.config
        if cfg.max_usd_per_day > 0:
            spent = self.memory.spent_today()
            if spent >= cfg.max_usd_per_day:
                raise BudgetExceeded(f"daily cap reached: ${spent:.2f} of ${cfg.max_usd_per_day:.2f} (limits.max_usd_per_day)")
        if cfg.max_usd_per_call > 0:
            tokens = estimate_tokens("".join(text_of(m["content"]) for m in messages))
            worst = self.price(model, tokens, cfg.max_output_tokens)
            if worst is not None and worst > cfg.max_usd_per_call:
                raise BudgetExceeded(
                    f"{model} could cost up to ${worst:.2f} for this request, above the ${cfg.max_usd_per_call:.2f} per-call cap")

    # --- the one entry point ---

    def messages(self, prompt: str, thread: str, use_memory: bool, system: str | None,
                 history: list[dict[str, str]] | None = None) -> list[dict[str, str]]:
        """Return what a model is sent: the system text, shared memory, the thread so far, then the request.

        ``history`` (earlier user/assistant messages supplied by a client that keeps its own
        conversation, such as a chat app) replaces the thread read from shared memory.
        """
        parts = [system or SYSTEM]
        if use_memory:
            block = self.memory.context(prompt, self.config.memory_chars)
            if block:
                parts.append(block)
        out = [{"role": "system", "content": "\n\n".join(parts)}]
        if history is not None:
            out += [{"role": m["role"], "content": str(m["content"])} for m in history if m.get("role") in ("user", "assistant")]
        else:
            for turn in self.memory.turns(thread, self.config.history_turns):
                if turn.role in ("user", "assistant"):
                    out.append({"role": turn.role, "content": turn.content})
        out.append({"role": "user", "content": prompt})
        return out

    def decide(self, prompt: str, *, slot: str | None = None, effort: str = "auto", context_text: str = "",
               router: str | None = None, pinned: bool = False, inputs: Inputs | None = None, goal: str = "auto",
               private: bool | None = None) -> Decision:
        """Classify and route ``prompt`` with the router in force; ``pinned`` when the user named a slot or model.

        ``private`` True keeps the request on your machine, False lets it leave, and None decides from
        its text (``[privacy] auto``). That step comes last, so no router or table can override it.
        """
        name = chosen(self.config.router, router)
        rules_task = classify(prompt)
        task, overhead, failed = rules_task, None, ""
        if name == "jev" and not (slot or pinned):
            try:
                task, overhead, _ = self.jev.classify(prompt, rules_task, self.config.jev_min_confidence)
            except JevError as exc:
                failed = str(exc)[:120]
        if name == "rules" and task.kind == "general" and self.config.classify_general and not (slot or pinned):
            task, overhead = self._classify_general(prompt, task)
        decision = route(prompt, self.config, slot=slot, effort=effort, context_text=context_text, task=task,
                         inputs=inputs, goal=goal)
        decision.router = "manual" if (slot or pinned) else name
        decision.overhead_cost = overhead
        if name == "learned" and not (slot or pinned) and not decision.inputs:
            self._learned_step(prompt, decision)
        if failed:
            decision.reasons.append(f"Jev failed ({failed}), so the rules decided")
        if not (slot or pinned) and not decision.ordered:
            with self._lock:
                self.tuning.apply(decision, self.config.slot)
            if (self.config.explore > 0 and name in ("rules", "jev") and len(decision.candidates) > 1
                    and self.random.random() < self.config.explore):
                decision.candidates[0], decision.candidates[1] = decision.candidates[1], decision.candidates[0]
                decision.explored = True
                decision.reasons.append(f"Exploring: the second choice answers this time (explore = {self.config.explore:g})")
        if name in HOSTED and not (slot or pinned):
            hosted = HOSTED[name]
            decision.candidates = [hosted] + [m for m in decision.candidates if m != hosted]
            decision.reasons.append(f"The router is {name}: it picks the model, and the '{decision.slot}' slot is the fallback")
        if decision.goal == "fastest" and not pinned:
            self._fastest_first(decision)
        if self.config.local_first and decision.slot == "quick" and not (slot or pinned) and decision.goal != "best":
            local = [m for m in self.config.local_models() if m not in decision.candidates[:1]]
            if local:
                decision.candidates = local + [m for m in decision.candidates if m not in local]
                decision.reasons.append(f"Local first: {', '.join(local)} on your machine tries it before the cloud models")
        reason = "you marked it private" if private else (
            looks_private(prompt) and f"it contains {looks_private(prompt)}" if private is None and self.config.private_auto else "")
        if reason:
            self._keep_local(decision, reason)
        return decision

    def speeds(self, limit: int = 500) -> dict[str, float]:
        """Return each model's median answer time in seconds over its recent answers (models with at least three)."""
        times: dict[str, list[float]] = {}
        for turn in self.memory.recent(limit):
            seconds = turn.meta.get("seconds") if turn.role == "assistant" else None
            if turn.model and isinstance(seconds, (int, float)) and seconds > 0:
                times.setdefault(turn.model, []).append(float(seconds))
        return {m: sorted(v)[len(v) // 2] for m, v in times.items() if len(v) >= 3}

    def _fastest_first(self, decision: Decision) -> None:
        measured = self.speeds()
        known = sorted((m for m in decision.candidates if m in measured), key=lambda m: measured[m])
        if known:
            decision.candidates = known + [m for m in decision.candidates if m not in measured]
            decision.reasons.append(f"The goal is the fastest answer: {known[0]} has answered fastest lately "
                                    f"(median {measured[known[0]]:.1f} s)")
        else:
            decision.reasons.append("The goal is the fastest answer, but no model has three timed answers yet, so the order stands")

    def _keep_local(self, decision: Decision, reason: str) -> None:
        local = self.config.local_models()
        decision.private = reason
        decision.candidates = [m for m in decision.candidates if m in local] or local
        if decision.candidates:
            decision.reasons.append(f"It stays on your machine because {reason}: only {', '.join(decision.candidates)} may answer,"
                                    " and its text is left out of Langfuse and the JSON-lines copy")
        else:
            decision.reasons.append(f"It must stay on your machine because {reason}, and no local model is configured")

    def _learned_step(self, prompt: str, decision: Decision) -> None:
        from crossvet.chat.learned import load

        model = load(self.memory)
        if model is None:
            decision.reasons.append("The learned router has not been trained yet (`crossvet chat learn`), so the rules decided")
            return
        slot, confidence = model.predict(prompt)
        if confidence < self.config.learned_min_confidence or slot == decision.slot:
            decision.reasons.append(f"The learned router agrees or is unsure ({slot}, p={confidence:.2f}), so the rules' slot stands")
            return
        candidates = self.config.slot(slot)
        if candidates:
            decision.slot, decision.candidates = slot, candidates
            decision.reasons.append(f"The learned router, trained on {model.examples} rated answers, moves it to '{slot}' "
                                    f"(p={confidence:.2f})")

    def _classify_general(self, prompt: str, rules_task: Task) -> tuple[Task, float | None]:
        """Ask a small model to name the kind of a request the rules call "general"; code reads its one-word answer.

        Anything but exactly one listed kind, a failure, or the daily cap leaves the rules' answer.
        The difficulty stays the rules' own.
        """
        setting = self.config.classify_general
        model = (self.config.slot("quick") or [""])[0] if setting == "quick" else setting
        if not model:
            return Task("general", rules_task.difficulty, rules_task.reason + "; no quick model to ask, so it stays general",
                        rules_task.wants_json), None
        messages = classifier_prompt(prompt)
        try:
            self._guard_budget(model, messages)
            reply = self._call(model, messages, 5)
        except (BudgetExceeded, ProviderError, RuntimeError) as exc:
            why = "the daily cap is reached" if isinstance(exc, BudgetExceeded) else f"{model} failed"
            return Task("general", rules_task.difficulty, f"{rules_task.reason}; {why}, so it stays general",
                        rules_task.wants_json), None
        cost = reply.cost if reply.cost is not None else self.price(model, reply.input_tokens, reply.output_tokens)
        kind = read_kind(reply.text)
        if kind is None or kind == "general":
            said = (reply.text or "").strip()[:30] or "nothing"
            return Task("general", rules_task.difficulty, f'{rules_task.reason}; {model} said "{said}", so it stays general',
                        rules_task.wants_json), cost
        return Task(kind, rules_task.difficulty, f"the rules found no specific kind and {model} classified it as {kind}",
                    rules_task.wants_json), cost

    def _check_with_jev(self, prompt: str, reply: Reply) -> tuple[str, float | None]:
        """Return a problem when Jev says the answer misses the request ("" otherwise), and the check's cost."""
        if self.config.check != "jev" or not reply.text.strip():
            return "", None
        try:
            probability, cost = self.jev.addresses(prompt, reply.text)
        except JevError:
            return "", None  # the check fails open: code checks already passed
        if probability < self.config.check_threshold:
            return f"Jev: does not address the request (p={probability:.2f})", cost
        return "", cost

    def _prepare(self, prompt: str, thread: str | None, model: str | None, slot: str | None, effort: str, author: str,
                 use_memory: bool, system: str | None, save: bool, history: list[dict[str, str]] | None,
                 router: str | None, parts: list[dict[str, Any]] | None = None, goal: str = "auto",
                 private: bool | None = None) -> tuple[str, list[dict[str, Any]], Decision]:
        """Check the request, build what the model is sent and route it; return ``(thread, messages, decision)``.

        ``parts`` is the request's content when it carries images, audio or files (OpenAI-style parts).
        """
        inputs = detect(parts, prompt)
        if inputs.audio and self.config.transcribe:
            prompt, parts = self._transcribe(prompt, inputs.parts)
            inputs = detect(parts, prompt)
        if (not prompt or not prompt.strip()) and not inputs.parts:
            raise ValueError("the request is empty")
        thread = thread or new_thread()
        with self._lock:
            messages = self.messages(prompt, thread, use_memory, system, history)
        if inputs.parts:
            messages[-1]["content"] = inputs.parts
        context_text = "".join(text_of(m["content"]) for m in messages[:-1])
        if model:
            providers.split(model)  # validates the name
        decision = self.decide(prompt, slot=slot, effort=effort, context_text=context_text, router=router, pinned=bool(model),
                               inputs=inputs, goal=goal, private=private)
        if model and decision.private and model not in self.config.local_models():
            raise NoModel(f"this request stays on your machine ({decision.private}), and {model} is not a local model")
        keep = self.config.quick_history_turns
        if decision.slot == "quick" and not model and len(messages) - 2 > 2 * keep:
            messages = [messages[0]] + (messages[1:-1][-2 * keep:] if keep else []) + [messages[-1]]
            decision.reasons.append(f"A quick model is answering, so only the last {keep} turn(s) of the conversation are sent")
        if model:
            decision.candidates = [model]
            decision.reasons.append(f"You named the model {model}")
            if save:
                self._note_switch(thread, model, author)
        if not decision.candidates:
            if decision.private:
                raise NoModel(f"this request stays on your machine ({decision.private}), but no local model is configured:"
                              " add an ollama:... or local:... model to a slot, or list one under [privacy] models")
            raise NoModel("no model is configured: run `crossvet chat init`, or pass --model provider:model")
        return thread, messages, decision

    def _transcribe(self, prompt: str, parts: list[dict[str, Any]]) -> tuple[str, list[dict[str, Any]]]:
        """Replace each audio part with its transcript (``[inputs] transcribe``); the rest of the parts stay."""
        texts, kept = [], []
        for part in parts:
            if part.get("type") == "input_audio":
                try:
                    texts.append(self._transcriber(self.config.transcribe, part))
                except ProviderError as exc:
                    raise ProviderError(f"transcription with {self.config.transcribe} failed: {exc}") from exc
            elif part.get("type") not in (None, "text", "input_text"):
                kept.append(part)
        heard = "\n\n".join(f"[transcribed audio]\n{t}" for t in texts if t)
        prompt = "\n\n".join(x for x in (prompt, heard) if x)
        return prompt, ([{"type": "text", "text": prompt}] + kept) if kept else []

    def ask(self, prompt: str, *, thread: str | None = None, model: str | None = None, slot: str | None = None,
            effort: str = "auto", author: str = "cli", use_memory: bool = True, system: str | None = None,
            want_json: bool | None = None, save: bool = True, history: list[dict[str, str]] | None = None,
            router: str | None = None, parts: list[dict[str, Any]] | None = None, goal: str = "auto",
            private: bool | None = None) -> Answer:
        """Answer ``prompt`` with the model the router picks (or ``model``), and save both turns."""
        thread, messages, decision = self._prepare(prompt, thread, model, slot, effort, author, use_memory, system,
                                                   save, history, router, parts, goal, private)
        needs_json = decision.task.wants_json if want_json is None else want_json
        attempts: list[Attempt] = []
        final: Reply | None = None
        extra = [decision.overhead_cost] if decision.overhead_cost is not None else []
        for candidate in decision.candidates:
            with self._lock:
                self._guard_budget(candidate, messages)
            try:
                reply = self._call(candidate, messages, self.config.max_output_tokens)
            except ProviderError as exc:
                attempts.append(Attempt(candidate, False, str(exc)[:200]))
                continue
            cost = reply.cost if reply.cost is not None else self.price(candidate, reply.input_tokens, reply.output_tokens)
            problem = check(reply, needs_json)
            if not problem:
                problem, check_cost = self._check_with_jev(prompt, reply)
                if check_cost is not None:
                    extra.append(check_cost)
            attempts.append(Attempt(candidate, not problem, problem, cost, reply.seconds))
            if not problem:
                final = reply
                break
            final = final or reply  # keep the first flawed answer in case every model fails the check
        if final is None:
            raise ProviderError(failure_message(attempts))
        answered_by = next((a.model for a in attempts if a.ok), final.model)
        known = [a.cost for a in attempts if a.cost is not None] + extra
        total = sum(known) if known else None
        answer = Answer(final.text, answered_by, thread, decision, attempts, total, final.input_tokens, final.output_tokens,
                        served_by=str(final.extra.get("served_by", "")), cached_tokens=int(final.extra.get("cached_tokens", 0) or 0))
        if save:
            self._save(answer, prompt, author, save_prompt=True)
        return answer

    def ask_stream(self, prompt: str, *, thread: str | None = None, model: str | None = None, slot: str | None = None,
                   effort: str = "auto", author: str = "cli", use_memory: bool = True, system: str | None = None,
                   history: list[dict[str, str]] | None = None, router: str | None = None,
                   parts: list[dict[str, Any]] | None = None, goal: str = "auto",
                   private: bool | None = None) -> Iterator[str | Answer]:
        """Like ``ask``, but yield the answer's text as it arrives, then the finished ``Answer``.

        A model that fails before sending any text is skipped for the next one, as in ``ask``. Text
        already sent can't be taken back, so a problem found after that (cut off at the output limit,
        broken JSON, a dropped connection) is recorded on the answer and no other model is tried.
        The Jev answer check is not run on streamed answers.
        """
        thread, messages, decision = self._prepare(prompt, thread, model, slot, effort, author, use_memory, system,
                                                   True, history, router, parts, goal, private)
        attempts: list[Attempt] = []
        final: Reply | None = None
        extra = [decision.overhead_cost] if decision.overhead_cost is not None else []
        for candidate in decision.candidates:
            with self._lock:
                self._guard_budget(candidate, messages)
            pieces = self._stream(candidate, messages, self.config.max_output_tokens)
            sent = False
            try:
                for item in pieces:
                    if isinstance(item, Reply):
                        final_reply = item
                        break
                    sent = True
                    yield item
                else:
                    raise ProviderError("the stream ended without a reply")
            except ProviderError as exc:
                if sent:
                    raise
                attempts.append(Attempt(candidate, False, str(exc)[:200]))
                continue
            reply = final_reply
            reply.model = reply.model or candidate
            cost = reply.cost if reply.cost is not None else self.price(candidate, reply.input_tokens, reply.output_tokens)
            problem = check(reply, decision.task.wants_json)
            if reply.raw_stop == "error" and not problem:
                problem = "the connection dropped before the answer finished"
            attempts.append(Attempt(candidate, not problem, problem, cost, reply.seconds))
            final = final or reply
            if sent or not problem:
                final = reply
                break
        if final is None:
            raise ProviderError(failure_message(attempts))
        answered_by = next((a.model for a in attempts if a.ok), final.model)
        known = [a.cost for a in attempts if a.cost is not None] + extra
        answer = Answer(final.text, answered_by, thread, decision, attempts, sum(known) if known else None,
                        final.input_tokens, final.output_tokens, served_by=str(final.extra.get("served_by", "")),
                        cached_tokens=int(final.extra.get("cached_tokens", 0) or 0))
        self._save(answer, prompt, author, save_prompt=True)
        yield answer

    def _save(self, answer: Answer, prompt: str, author: str, save_prompt: bool) -> None:
        with self._lock:
            if save_prompt:
                self.memory.add_turn(answer.thread, author, "user", prompt + (
                    f"\n\n[with {' and '.join(answer.decision.inputs)}]" if answer.decision.inputs else ""))
            text = answer.text or ("[tool calls: " + ", ".join(
                str((c.get("function") or {}).get("name", "?")) for c in answer.tool_calls) + "]" if answer.tool_calls else "")
            answer.turn_id = self.memory.add_turn(answer.thread, author, "assistant", text, model=answer.model,
                                                  cost=answer.cost, meta=self.meta(answer))
        self._record(answer, prompt, author, text)

    def _record(self, answer: Answer, prompt: str, app: str, text: str) -> None:
        decision = answer.decision
        self.recorder.turn(TurnRecord(
            trace_id=self.trace_id(answer.turn_id), turn_id=answer.turn_id, thread=answer.thread, app=app, model=answer.model,
            kind=decision.task.kind, difficulty=decision.task.difficulty, slot=decision.slot, why=decision.explain(),
            router=decision.router, served_by=answer.served_by,
            prompt=None if decision.private else prompt, answer=None if decision.private else text,
            attempts=[{"model": a.model, "ok": a.ok, "problem": a.problem, "cost": a.cost} for a in answer.attempts],
            cost=answer.cost, input_tokens=answer.input_tokens, output_tokens=answer.output_tokens,
            seconds=round(sum(a.seconds for a in answer.attempts), 2), escalated=answer.escalated,
            tools=bool(answer.tool_calls), explored=decision.explored))

    # --- ratings ---

    def trace_id(self, turn_id: int) -> str:
        """Return the trace id a turn is recorded under."""
        return trace_id_for(self.memory.id, turn_id)

    def rate(self, turn_id: int, name: str, value: float, comment: str = "", source: str = "") -> int:
        """Save a score on an answer and copy it to the sinks; return its id."""
        with self._lock:
            rating = self.memory.add_rating(turn_id, name, value, comment, source)
        self.recorder.score(self.trace_id(turn_id), name, value, comment)
        return rating

    def feedback(self, good: bool, *, thread: str | None = None, turn_id: int | None = None, comment: str = "",
                 source: str = "") -> int:
        """Rate an answer good or bad: ``turn_id``, else the last answer in ``thread``, else the latest answer anywhere."""
        if turn_id is None:
            last = self.memory.last_answer(thread) if thread else next((t for t in self.memory.recent(200) if t.role == "assistant"), None)
            if last is None:
                raise ValueError("there is no answer to rate yet")
            turn_id = last.id
        return self.rate(turn_id, "user-feedback", 1.0 if good else 0.0, comment, source)

    def _note_switch(self, thread: str, model: str, source: str) -> None:
        last = self.memory.last_answer(thread)
        if last is not None and last.model and last.model != model:
            self.rate(last.id, "switched", 1.0, f"next turn asked for {model}", source)

    def retry(self, thread: str, *, stronger: bool = True, author: str = "cli") -> Answer:
        """Ask the thread's last question again, one slot up the ladder (or with the same route)."""
        turns = self.memory.turns(thread, 50)
        answers = [t for t in turns if t.role == "assistant"]
        questions = [t for t in turns if t.role == "user"]
        if not questions:
            raise ValueError("nothing to retry in this thread")
        previous = answers[-1].meta.get("slot") if answers else None
        slot = stronger_slot(previous or "balanced") if stronger else previous
        if answers:
            self.rate(answers[-1].id, "retried", 1.0, "asked again one slot up" if stronger else "asked again", author)
        return self.ask(questions[-1].content, thread=thread, slot=slot, author=author)

    # --- agents: pass the whole request through ---

    def relay(self, body: dict[str, Any], *, thread: str, author: str = "api", model: str | None = None,
              slot: str | None = None, effort: str = "auto", router: str | None = None) -> tuple[dict[str, Any], Answer]:
        """Route an OpenAI-style request with tools and pass it through unchanged; return the raw reply and the answer."""
        messages = list(body.get("messages") or [])
        users = [m for m in messages if m.get("role") == "user"]
        if not users:
            raise ValueError("the request has no user message")
        prompt = user_text(users[-1])
        context_text = "".join(user_text(m) for m in messages[:-1])
        looping = in_tool_loop(messages)
        decision = self.decide(prompt, slot=slot, effort=effort, context_text=context_text, router=router,
                               pinned=bool(model))
        if model:
            providers.split(model)
            decision.candidates = [model]
            decision.reasons.append(f"You named the model {model}")
            if not looping:
                self._note_switch(thread, model, author)
        elif looping:
            previous = self.memory.last_model(thread)
            if previous:
                decision.candidates = [previous] + [m for m in decision.candidates if m != previous]
                decision.reasons.append(f"This continues a tool loop, so {previous}, which started it, answers")
        usable = [m for m in decision.candidates if providers.split(m)[0] != "anthropic"]
        if len(usable) < len(decision.candidates):
            decision.reasons.append("Direct Anthropic models were skipped: tool calls pass through OpenAI-style APIs only")
        decision.candidates = usable
        if not usable:
            raise NoModel("no OpenAI-style model for this slot: add openrouter:<maker>/<model> models to it")
        attempts: list[Attempt] = []
        for candidate in usable:
            with self._lock:
                self._guard_budget(candidate, [{"content": user_text(m)} for m in messages])
            try:
                raw, reply = self._relay(candidate, body)
            except ProviderError as exc:
                attempts.append(Attempt(candidate, False, str(exc)[:200]))
                continue
            cost = reply.cost if reply.cost is not None else self.price(candidate, reply.input_tokens, reply.output_tokens)
            calls = reply.extra.get("tool_calls") or []
            problem = "" if calls else check(reply, False)
            if problem == "stopped at the output limit" and calls:
                problem = ""
            attempts.append(Attempt(candidate, not problem, problem, cost, reply.seconds))
            if problem:
                continue
            known = [a.cost for a in attempts if a.cost is not None] + (
                [decision.overhead_cost] if decision.overhead_cost is not None else [])
            answer = Answer(reply.text, candidate, thread, decision, attempts, sum(known) if known else None,
                            reply.input_tokens, reply.output_tokens, served_by=str(reply.extra.get("served_by", "")),
                            tool_calls=list(calls))
            self._save(answer, prompt, author, save_prompt=not looping)
            return raw, answer
        raise ProviderError(failure_message(attempts))

    @staticmethod
    def meta(answer: Answer) -> dict[str, Any]:
        """Return what is saved with an answer so the choice can be audited later."""
        return {
            "kind": answer.decision.task.kind,
            "difficulty": answer.decision.task.difficulty,
            "slot": answer.decision.slot,
            "router": answer.decision.router,
            "why": answer.decision.explain(),
            "attempts": [{"model": a.model, "ok": a.ok, "problem": a.problem, "cost": a.cost} for a in answer.attempts],
            "served_by": answer.served_by,
            "tools": bool(answer.tool_calls),
            "explored": answer.decision.explored,
            "goal": answer.decision.goal,
            "private": bool(answer.decision.private),
            "inputs": answer.decision.inputs,
            "seconds": round(sum(a.seconds for a in answer.attempts if a.ok) or sum(a.seconds for a in answer.attempts), 2),
            "first_choice": answer.decision.candidates[0] if answer.decision.candidates else "",
            "usage": {"input": answer.input_tokens, "output": answer.output_tokens, "cached": answer.cached_tokens},
        }


def failure_message(attempts: list[Attempt]) -> str:
    """One line for when every model failed; a single missing key is named once, with the fix."""
    problems = {a.problem for a in attempts}
    if len(problems) == 1 and (only := problems.pop() or "").endswith(" is not set"):
        name = only.removesuffix(" is not set")
        return (f"{name} is not set: add it to .env in this folder (or export it), then try again. "
                "`crossvet chat doctor` checks every slot.")
    return "every model failed: " + "; ".join(f"{a.model}: {a.problem}" for a in attempts)


def _whole(call: Caller, model: str, messages: list[dict[str, str]], max_tokens: int) -> Iterator[str | Reply]:
    """Stream a caller's finished reply as one piece of text, then the reply (the call starts on the first read)."""
    reply = call(model, messages, max_tokens)
    if reply.text:
        yield reply.text
    yield reply
