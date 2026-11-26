# Crossvet

**One chat, any model.** Use Claude, ChatGPT, Gemini, Grok or a model on your own machine from the chat you already use (Hermes, Cursor, Claude Code, Codex or a terminal). Name the model yourself, or name `auto` and Crossvet chooses one, says why, and tries the next model when an answer fails a check. Every answer shows which model gave it and what it cost, and spend caps stop a call before it is made.

[![CI](https://github.com/j-zulick/crossvet/actions/workflows/ci.yml/badge.svg)](https://github.com/j-zulick/crossvet/actions/workflows/ci.yml)
[![CodeQL](https://github.com/j-zulick/crossvet/actions/workflows/codeql.yml/badge.svg)](https://github.com/j-zulick/crossvet/actions/workflows/codeql.yml)
[![Release](https://img.shields.io/github/v/release/j-zulick/crossvet)](https://github.com/j-zulick/crossvet/releases/latest)
[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue)](pyproject.toml)
[![License: MIT](https://img.shields.io/badge/license-MIT-green)](LICENSE)

```
$ crossvet route "Write a Python function parse_listing(s) that turns '2021 Toyota Tacoma SR5 - 34,210 mi - $31,995' into a dict"
anthropic:claude-opus-5-5 answers. Kind of task: code (difficulty 2): it is about code ("Python"). Slot: strong;
goal: auto. If it fails, Crossvet tries openai:gpt-6.1-sol.

$ crossvet ask -m auto "Sarasota Ford is at 707 S Washington Blvd., Sarasota, FL 34236. What is its ZIP code? Number only."
34236
[anthropic:claude-haiku-5-5 · 55 in / 106 out · $0.0001 · 1.0 s · auto: quick slot, /why explains]

$ crossvet route "[private] Draft the deposit receipt for card 4111 1111 1111 1111"
crossvet: this request looks private ([private]), and no private model is set, so it was not sent anywhere. Add
[slots] private = ["ollama:..."] (a model on this computer), remove the private details, or name a model yourself.
```

From the released build: the `route` lines are its output (it calls no model), and the answer and its footer are from the [live run of 2026-11-26](docs/live-runs/2026-11-26-v3.0.0.md), on tasks from used-car dealer work in Sarasota, Florida.

## Quick start

```bash
uv tool install "git+https://github.com/j-zulick/crossvet@v3.0.0"
mkdir -p ~/.config/crossvet && cp .env.example ~/.config/crossvet/.env   # then fill in the keys you have
crossvet start
```

`crossvet start` checks your keys without calling a model, prints the settings for each app below, and starts the server. Three dependencies (httpx, the MCP Python SDK, python-dotenv); Python 3.11 to 3.13. More: [docs/SETUP.md](docs/SETUP.md).

## Use it from the chat you already have

| Your chat | Connect once | Pick the model |
|---|---|---|
| **Hermes**, or any app that takes an OpenAI-style URL | Custom provider at `http://127.0.0.1:8787/v1` (keep `crossvet start` running) | The app's model menu (Crossvet lists your models and `auto` at `/v1/models`), or type `/model NAME` |
| **Claude Code** | `claude mcp add --scope user crossvet -- crossvet mcp` | Ask it to use `ask_model` with the model you want, or `ask` to let Crossvet choose |
| **Codex** | `codex mcp add crossvet -- crossvet mcp` | The same |
| **Cursor** | `crossvet start --no-serve` prints the `~/.cursor/mcp.json` entry | The same |
| A terminal | `crossvet chat --model opus`, `crossvet chat --model auto` or `crossvet ask -m sol "..."` | `/model NAME` |

A model is named `provider:model` (`anthropic:claude-opus-5-5`, `openai:gpt-6.1-sol`, `google:...`, `xai:...`, `openrouter:vendor/model`, `ollama:...`) or by a short name you set (`opus`, `sonnet`, `sol`, `luna`). A request that names no model goes to your `default_model`. `auto`, `crossvet/<slot>` (`crossvet/strong`) and `crossvet/<goal>` (`crossvet/cheapest`) let Crossvet choose.

In any of them, typed as a whole message: `/model NAME`, `/models`, `/cost`, `/why` (why auto chose), `/good` and `/bad` (rate the last answer), `/retry stronger` (ask again one slot up).

## How it works

```mermaid
flowchart LR
    A["Your chat<br/>Hermes · Cursor · Claude Code · Codex · terminal"] --> B{"Model named?"}
    B -- "a model" --> D["That model"]
    B -- "auto / slot / goal" --> R["Rules: private? image? long?<br/>kind of task → slot → model"]
    R --> D
    D --> C{"Spend caps,<br/>refused keys"}
    C -- "allowed" --> V["That vendor's API"]
    C -- "stopped" --> X["Refused before any call"]
    V --> K{"auto: error, empty,<br/>bad JSON?"}
    K -- "yes, nothing shown yet" --> N["Next model on the ladder"]
    K -- "no" --> E["Answer + model + cost + why"]
    E --> F["Local log + lab file (SQLite)"]
```

- **A named model is never switched.** No routing, no fallback, no silent retries for it. If a call fails, the error names the model and you pick another.
- **`auto` explains itself.** The choice is made in code from the request alone: private-looking text stays on your machine or is refused; images go to a vision model; otherwise the kind of task (code, review, writing, summarize, extract, translate, reasoning, quick, general) picks a slot. `/why` shows the reason and every attempt. Escalation happens only after an error, an empty answer or invalid JSON, and only before anything is shown.
- **It learns only when you say so.** `/good` and `/bad` record ratings. `crossvet tune` proposes a better model for a kind of task from them, and nothing changes until you accept; every change rolls back.
- **Several vendors when you want them.** `compare` asks several models at once; `challenge` has another vendor check an answer, with its verdict read in code; `replay` runs your past questions on another model and a blind judge picks the better answer.
- **Agents keep their tools.** Hermes and other agents send tools and tool results, and Crossvet passes them to the model, streamed when the app streams. OpenAI models get them through the Responses API (their current models refuse tools on chat completions), with their encrypted reasoning kept and sent back across tool steps; Anthropic models through Anthropic's OpenAI-compatible endpoint. A request field a vendor has no place for is reported, never dropped silently.
- **Costs are visible and capped.** Each answer is priced from the vendor's list price (or OpenRouter's reported cost). A daily cap and a per-call worst-case cap stop a call before it is made. A provider that rejects your key or reports a billing problem is not called again until restart.
- **Two local files.** Every question and answer goes to one append-only SQLite log shared by every app; decisions, ratings, notes and accepted routes go to a second file next to it. `report`, `dashboard`, `export`, `sync` (Langfuse), `backup` and `restore` work on both.

## Tested with real API calls

`tests/live/` calls the real APIs (`CROSSVET_LIVE=1 uv run pytest tests/live`). The [run of 2026-11-26](docs/live-runs/2026-11-26-v3.0.0.md) passed all 21 checks with OpenAI and Anthropic keys, for **$0.054**:

- each of six models answered when named; through the server, `/model` switched vendors mid-conversation, the answer streamed, and `/cost` showed both;
- agents' tool calls round-tripped (call `lookup_vin`, send the result, get the price) with Claude Sonnet, GPT-6.1 Sol and GPT-6 Luna, including streamed loops with two tool calls at once and OpenAI reasoning kept across tool steps;
- `auto` sent the ZIP-code question to the quick slot (Claude Haiku, right answer) and the parsing function to the strong slot (Claude Opus);
- a model that doesn't exist failed with HTTP 404 and `auto` moved to the next model on the ladder, recording both attempts;
- `compare` got answers from both vendors; `challenge` had Claude Sonnet check a wrong answer from the other vendor and return `wrong` with the reasons;
- on four benchmark cases, Claude Haiku scored 1.0 on all four and GPT-6 Luna on three (0.5 on a 40-word summary); a per-call cap and a rejected key stopped calls before they were made; the MCP server listed its 14 tools, answered, and explained a route.

The live runs found four problems before release, all fixed and covered by tests: "ZIP code" counted as program code; a short fact plus a question was not counted as quick; parallel calls could collide on the log's one SQLite connection; and a lab file could end up next to the wrong log. The full benchmark (28 cases, six models, $0.48) is in [docs/benchmarks/2026-11-25](docs/benchmarks/2026-11-25/README.md). Not tested live yet: the Hermes, Cursor, Claude Code and Codex apps themselves, Langfuse sync, handoffs, Google, xAI, OpenRouter and local models.

## Project layout

About 4,600 lines of Python in 18 modules, with 171 offline tests (some built from replies recorded from the real APIs) and 21 live ones.

| File | What it does |
|---|---|
| `src/crossvet/core.py` | The one path every request takes: resolve or choose, check the caps, call, escalate (auto only), log |
| `src/crossvet/routing.py`, `classify.py` | `auto`: private requests, inputs, the kind of task, slots, goals, the ladder, and the explanation |
| `src/crossvet/providers.py` | OpenAI, Anthropic, Google, xAI, OpenRouter, Ollama and any OpenAI-compatible server through one function |
| `src/crossvet/relay.py` | Agents' requests with tools: streamed, translated for OpenAI's Responses API, reasoning kept across tool steps |
| `src/crossvet/server.py` | The OpenAI-compatible server for Hermes and other chat apps |
| `src/crossvet/mcp_server.py` | 14 MCP tools: `list_models`, `ask_model`, `recent_turns`, `ask`, `explain_route`, `compare_models`, `challenge`, `rate_answer`, notes and handoffs |
| `src/crossvet/multi.py`, `bench.py`, `tuning.py` | Compare, challenge, blind replay; the Sarasota benchmark; route proposals from ratings |
| `src/crossvet/lab.py`, `store.py`, `care.py`, `langfuse.py`, `handoff.py` | The lab file and the log; report, dashboard, export, backup; Langfuse sync; Claude Code and Codex handoffs |
| `src/crossvet/config.py`, `cli.py` | Settings (names, slots, routes, prices, limits); the `crossvet` command |

## Documentation

[Using Crossvet](docs/CHAT.md) · [Setup](docs/SETUP.md) · [Architecture](docs/ARCHITECTURE.md) · [Design decisions](docs/DESIGN-DECISIONS.md) · [Security model](docs/SECURITY-MODEL.md) · [What stays stable](docs/STABILITY.md) · [Moving to 3.0](docs/MIGRATING.md) · [Changelog](CHANGELOG.md)

## License

MIT. See [LICENSE](LICENSE) and [NOTICES.md](NOTICES.md).
