# Architecture

```
 Hermes / any OpenAI-style chat app ──HTTP──► server.py ─┐
 Cursor / Claude Code / Codex ──────MCP────► mcp_server.py ├─► hub.py ──► providers.py ──► OpenAI, Anthropic, Google, xAI,
 Terminal ─────────────────────────────────► cli.py ─────┘      │                          OpenRouter, Ollama, local servers
                                                                 ├─ classify.py / inputs.py   what kind of task, what it carries
                                                                 ├─ router.py / routing.py    which models to try, and why
                                                                 ├─ guard (in hub.py)         answer checks, escalation, caps,
                                                                 │                            refused accounts
                                                                 └─ memory.py / record.py     the store; copies to Langfuse
```

One request, start to finish:

1. **Classify.** Text rules (`classify.py`) name the kind of task (code, review, writing, summarize, extract, translate, reasoning, fresh, quick, general) and a difficulty from 1 to 3, with the reason in words. `inputs.py` notices images, audio, PDFs and pasted code. Optionally Jev, or a small model for "general" requests, names the kind instead; code accepts its answer only above a confidence.
2. **Route.** The kind picks a slot (quick, balanced, strong, fresh, long, vision, audio, reviewer); difficulty and `--effort` move it along quick → balanced → strong; a long input moves it to `long`. The routing table you tune (`tuning.py`) puts preferred models first and drops avoided ones; a goal (best, cheapest, fastest) reorders; a private request stays on a local model. The result is an ordered list of models and the reason.
3. **Call and guard.** `hub.py` calls the first model through `providers.py`. The next model is tried only after an error, an empty or cut-off answer, invalid JSON when JSON was asked for, or (optionally) a failed Jev answer check. Daily and per-call spend caps stop a call before it is made. A provider that refuses the account (401, 402, a quota or billing refusal) is skipped for the rest of the process.
4. **Record.** The turn (model, kind, slot, reason, attempts, tokens, cost, seconds, escalation) goes to the local SQLite store first, which refuses updates and deletes, then to Langfuse if configured. `/good` and `/bad` add ratings; `tune` turns ratings into proposed table changes that only you accept; the chat benchmark (`bench.py`) scores models per kind of task with answer keys and can write the table.

Settings: keys in `.env`, routing in `crossvet-chat.toml` ([`crossvet-chat.example.toml`](../crossvet-chat.example.toml)). Design records: [DESIGN-DECISIONS.md](DESIGN-DECISIONS.md).
