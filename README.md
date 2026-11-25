# Crossvet

**One chat that controls Claude, ChatGPT and other models.** Keep using Hermes, Cursor or any chat app you like: Crossvet sits behind it, sends each request to a model suited to it, and tells you which model answered, why, and what it cost. Every decision that matters (which kind of task, which model, whether an answer passed its check, whether a spend cap stops a call) is made in code, so you can read it and change it.

[![CI](https://github.com/j-zulick/crossvet/actions/workflows/ci.yml/badge.svg)](https://github.com/j-zulick/crossvet/actions/workflows/ci.yml)

```
> Write a Python function that parses "2021 Toyota Tacoma SR5 - 34,210 mi - $31,995" into year, make, model, trim, miles and price.
...
[anthropic:claude-opus-5-5 · code → strong · $0.0413]

> Is a 2019 Honda CR-V with 48,000 miles low or high mileage for its age? One sentence.
At about 6,900 miles per year, a 2019 Honda CR-V with 48,000 miles has low mileage for its age.
[openai:gpt-6-luna · quick → quick · $0.0000]
```

Both answers are from the [live run of 2026-11-25](docs/live-runs/2026-11-25.md), on tasks from used-car dealer work in Sarasota, Florida.

## Quick start

```bash
uv tool install "crossvet[langfuse] @ git+https://github.com/j-zulick/crossvet@v1.0.0"
mkdir ~/crossvet-work && cd ~/crossvet-work
# put your keys in .env (copy .env.example from the repository): OPENAI_API_KEY, ANTHROPIC_API_KEY, ...
crossvet chat start
```

`crossvet chat start` writes a settings file from the keys you have, checks them without calling a model, prints what to paste into Hermes and Cursor, and starts the server. The base install has three dependencies (httpx, the MCP SDK, python-dotenv); `[langfuse]` adds a copy of every turn and rating in Langfuse. Details: [docs/SETUP.md](docs/SETUP.md).

## Use it from the chat you already have

| Your chat | How it connects | Settings |
|---|---|---|
| **Hermes**, Open WebUI, LibreChat, any app that takes an OpenAI-style URL | `crossvet chat serve` (started by `chat start`) | Base URL `http://127.0.0.1:8787/v1`, model `auto` |
| **Cursor**, Claude Code, Codex | MCP tools: `ask`, `ask_model`, `compare_models`, `challenge`, `explain_route`, `rate_answer` and seven more | `crossvet chat mcp` (`chat start --no-serve` prints the entry) |
| A terminal | `crossvet chat` | — |

Typed as a whole message in any of them: `/why` (why that model), `/model NAME` (use this model; `/model auto` goes back), `/retry stronger` (ask again, one step up), `/good` and `/bad` (rate the answer), `/cost`.

## How a request is routed

1. **What kind of task.** Text rules name the kind (code, review, writing, summarize, extract, translate, reasoning, fresh, quick, general) and a difficulty from 1 to 3, with the reason in words. Images, audio, PDFs and pasted code are noticed too.
2. **Which models.** The kind picks a slot (quick, balanced, strong, fresh, long, vision, audio); difficulty moves it along quick → balanced → strong; your routing table puts preferred models first. An image goes to the vision slot; a long input to the long slot; a private request stays on a local model.
3. **The guard.** The next model is tried only after an error, an empty or cut-off answer, or broken JSON. Daily and per-call spend caps stop a call before it is made. A provider that rejects your key or reports a billing problem is not called again until you restart, so it can't keep costing you.
4. **The record.** Every turn (model, kind, slot, reason, tokens, cost) is saved in one local SQLite file and copied to Langfuse. Your `/good` and `/bad` ratings turn into proposed routing changes that only you accept.

Providers: OpenAI, Anthropic, Google, xAI, OpenRouter (most other vendors with one key), Ollama and any OpenAI-compatible server on your machine. Full guide: [docs/CHAT.md](docs/CHAT.md).

## Tested with real API calls

`tests/live/` makes real calls with the keys in `.env` (`CROSSVET_LIVE=1 uv run pytest tests/live`). The [run of 2026-11-25](docs/live-runs/2026-11-25.md) passed all 12 checks with OpenAI and Anthropic for an estimated **$0.08**:

- both providers answered, and each request went to the slot its kind called for (code → strong, a quick question → quick, a customer reply → balanced);
- the server answered the way Hermes calls it, streamed, and answered `/why`;
- a chart sent as an image went to the vision slot and was read correctly;
- a per-call spend cap stopped a request before any model was called;
- with an invalid OpenAI key, Anthropic answered and OpenAI was not called again;
- two vendors answered side by side, and a model from another vendor challenged a claim;
- a rated turn reached Langfuse with its score;
- the MCP server, started the way Cursor starts it, listed its tools and answered.

The run found and fixed one serious bug: OpenAI's current models refuse the `max_tokens` field, so every OpenAI call failed until Crossvet sent `max_completion_tokens`. Not run live yet: the Hermes and Cursor apps themselves, Google, xAI, OpenRouter, Jev and local models, and the chat benchmark.

400 offline tests run on every change, with lint, CodeQL, a secret scan and an SBOM.

## Documentation

[Setup](docs/SETUP.md) · [Guide](docs/CHAT.md) · [Architecture](docs/ARCHITECTURE.md) · [Security model](docs/SECURITY-MODEL.md) · [Design decisions](docs/DESIGN-DECISIONS.md) · [What stays stable](docs/STABILITY.md) · [Live runs](docs/live-runs/) · [Changelog](CHANGELOG.md) · [Contributing](CONTRIBUTING.md) · [Agent guide](AGENTS.md)

MIT License. Credits: [NOTICES.md](NOTICES.md).
