# Architecture

```
 Hermes / any OpenAI-style app ──HTTP──► server.py ──────┐
 Claude Code / Codex / Cursor ───MCP───► mcp_server.py ──┼─► core.py ──► providers.py ──► OpenAI, Anthropic, Google, xAI,
                                                         │      │         relay.py (requests with tools)
 Terminal ─────────────────────────────► cli.py ─────────┘      │                         OpenRouter, Ollama, local servers
                                                                ├─ routing.py  auto: kind of task -> slot -> model (classify.py)
                                                                ├─ config.py   names, slots, routes, prices, limits
                                                                ├─ store.py    the log of turns (SQLite, append-only)
                                                                └─ lab.py      decisions, ratings, notes, routes, handoffs
 Built on the core: multi.py (compare, challenge, replay), review.py and review_bench.py, score.py (judge, shadow,
 calibration, leaderboard), bench.py, tuning.py, langfuse.py,
 care.py, handoff.py; service.py runs the server at login (launchd, systemd); Dockerfile and compose.yaml for a server
```

One request, start to finish:

1. **Name.** The entry point passes the model name it was given: the request's `model` field or the latest `/model NAME` (server), the `model` argument (MCP), or `--model` and `/model` (terminal). `config.resolve` turns a short name or `default` into `provider:model`; an unknown name is an error.
2. **Choose, only if asked.** When the name is `auto`, `crossvet/<slot>` or `crossvet/<goal>`, `routing.decide` makes a `Decision` from the request alone: private-looking text goes to the private slot or is refused; images to vision; very long requests to long; otherwise `classify.py` names the kind and difficulty, `[routes]` picks the slot, an accepted route from `lab.py` goes first, then (with `[router] use = "scores"`) the best-value model from the judged leaderboard, and the goal orders the slot. The rest of the slot, then the slots above it, form the ladder.
3. **Guard.** `core.Crossvet.check` runs before any call: a provider that refused the account earlier in this process is not called; today's logged spend must be under the daily cap; the worst-case cost of this call (request size plus the full output limit, at list price) must be under the per-call cap.
4. **Call.** `providers.py` sends the request to that vendor, with one output limit and one timeout, streaming the text. A request with tools goes through `relay.py` whole, streamed or not: chat completions for OpenAI-style providers, Anthropic's OpenAI-compatible endpoint for Anthropic, and OpenAI's Responses API for OpenAI (translated both ways, with the model's encrypted reasoning kept per tool call in the log's `relay_state` table and sent back with the results).
5. **Check and escalate (auto only).** `core.problem` decides in code whether an answer failed: an error, an empty answer, or invalid JSON when JSON was asked for. A failed attempt moves to the next model on the ladder, at most `[router] max_steps` times, as long as nothing has been streamed yet. A named model is never switched.
6. **Log.** `core.Crossvet._log` prices the answer (provider-reported cost, else list price) and appends the question and the answer, with model, tokens, cost and seconds, to the log. When Crossvet chose, the decision and every attempt go to the lab file, keyed by the answer's turn id.

Settings: keys in the environment or `.env`; everything else in `crossvet.toml` ([example](../crossvet.example.toml)). Design records: [DESIGN-DECISIONS.md](DESIGN-DECISIONS.md).
