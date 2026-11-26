# Architecture

```
 Hermes / any OpenAI-style app ──HTTP──► server.py ──────┐
 Claude Code / Codex / Cursor ───MCP───► mcp_server.py ──┼─► core.py ──► providers.py ──► OpenAI, Anthropic, Google, xAI,
                                                         │      │         relay.py (requests with tools)
 Terminal ─────────────────────────────► cli.py ─────────┘     │                         OpenRouter, Ollama, local servers
                                                                ├─ config.py   the name → provider:model, prices, limits
                                                                └─ store.py    the local log (SQLite, append-only)
```

One request, start to finish:

1. **Name.** The entry point passes the model name it was given: the request's `model` field or the latest `/model NAME` (server), the `model` argument (MCP), or `--model` and `/model` (terminal). `config.resolve` turns a short name or `default` into `provider:model`. It never chooses: an unknown name is an error.
2. **Guard.** `core.Crossvet.check` runs before any call: a provider that refused the account earlier in this process is not called; today's logged spend must be under the daily cap; the worst-case cost of this call (request size plus the full output limit, at list price) must be under the per-call cap.
3. **Call.** `providers.py` sends the request to that vendor, with one output limit and one timeout, streaming the text. A request with tools goes through `relay.py` whole, streamed or not: chat completions for OpenAI-style providers, Anthropic's OpenAI-compatible endpoint for Anthropic, and OpenAI's Responses API for OpenAI (translated both ways, with the model's encrypted reasoning kept per tool call in the log's `relay_state` table and sent back with the results).
4. **Log.** `core.Crossvet._log` prices the answer (provider-reported cost, else list price) and appends the question and the answer, with model, tokens, cost and seconds, to the log.

A failure at any step returns an error naming the model. Nothing is retried or re-routed.

Settings: keys in the environment or `.env`; everything else in `crossvet.toml` ([example](../crossvet.example.toml)). Design records: [DESIGN-DECISIONS.md](DESIGN-DECISIONS.md).
