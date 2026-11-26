# Design decisions

Each entry: the context, the decision, and what it costs. Entries for 1.x features that moved out of Crossvet in 2.0 are in the 1.x history (tag `v1.1.1`).

## 1. You name the model; Crossvet never chooses (2.0)
**Context.** Crossvet 1.x classified each request and routed it to a model it judged suitable. People who use several models usually already know which one they want, and a router that guesses adds a layer to understand and distrust.
**Decision.** Every request names its model, or gets the one `default_model` you set. No routing, no fallback to another model, no silent retry. Short names (`opus`, `sol`) make naming quick.
**Cost.** When a model fails, you pick another yourself. Routing and scoring are left to separate tools built on top.

## 2. Meet each chat where it is: an OpenAI-compatible server, MCP tools, and a terminal
**Context.** Hermes and most chat apps take an OpenAI base URL; Claude Code, Codex and Cursor take MCP servers.
**Decision.** One core (`core.py`) behind three thin entry points. The server lists your models at `/v1/models` so the app's own model menu works, and accepts `/model NAME` typed in any app.
**Cost.** `/model` typed in the chat has to be found in the history the app sends back; Crossvet strips those commands and its replies before a model sees the conversation.

## 3. Pass agents' tools through; translate only where a vendor requires it
**Context.** Agents such as Hermes send tools and tool results on every request. On 2026-11-26, OpenAI's gpt-6.1-sol, gpt-6.1-terra and gpt-6-luna all refused tools on chat completions (Sol refused them with any reasoning setting); Anthropic's native API uses a different tool format.
**Decision.** Requests with tools go through whole, streamed when the app streams (`relay.py`): OpenAI-style providers as they are, Anthropic through its OpenAI-compatible endpoint, OpenAI through the Responses API with a translation in each direction and `store: false`. Since 2.0.1:
- OpenAI's encrypted reasoning is requested (`include: reasoning.encrypted_content`), kept per tool-call id for 7 days, and sent back with the tool results, which is how a stateless client keeps a reasoning model's chain of thought across tool steps. Checked live on 2026-11-26: Sol at high effort reasoned before its tool call, and the kept reasoning was accepted on the next step.
- A field the Responses API has no place for is dropped and reported (`crossvet.dropped`), never silently.
- The translation is tested against replies recorded from the real APIs (`tests/unit/fixtures/`).
**Cost.** One exception to "nothing is resent": when OpenAI rejects kept reasoning (`invalid_encrypted_content`, for example after a key or organization change), the same request goes to the same model once more without it, and the response says so. Responses-only features beyond the chat-completions shape are not exposed.

## 4. Guards are code, and run before the call
**Context.** Spending money is the main way a multi-vendor chat goes wrong: a runaway agent loop, an expensive model on a huge input, a revoked key that keeps being called.
**Decision.** A daily cap, a per-call worst-case cap at list price, and a per-process block on a provider that refused the account (401, 402, or a quota or billing refusal, decided from the HTTP status and the error text). All three raise before the request leaves.
**Cost.** The caps are only as good as the prices: a model with no price counts as $0 (`doctor` lists them). The per-call estimate assumes the full output limit, so it is deliberately pessimistic.

## 5. One local, append-only log shared by every app
**Context.** Knowing what was asked, of which model, at what cost, matters more when several apps share one set of keys.
**Decision.** One SQLite file in WAL mode, with triggers that refuse updates and deletes. It keeps the 1.x table, so history carries over.
**Cost.** No search, export or retention tools in Crossvet itself; the file is plain SQLite for anything else.

## 6. A dated built-in model table; names and the default are yours
**Context.** A new user should get a working setup from their keys alone, and model ids and prices go stale.
**Decision.** `config.KNOWN` lists the models this project calls in its live tests, with list prices and the date they were checked. Without a settings file, the models your keys can call are offered with short names and a default. `crossvet init` writes that as a file you edit.
**Cost.** The table needs updating as vendors release models; anything not in it works by its full name, with a price you add.

## 7. Install from GitHub; keys from the environment or `.env`
**Context.** MCP apps start `crossvet mcp` in a folder of their choosing, so a `.env` only in a working folder is missed.
**Decision.** Keys come from the environment, then `./.env`, then `~/.config/crossvet/.env` (python-dotenv, never overriding the environment). Releases install from tags on GitHub.
**Cost.** No PyPI package; `uv tool install` takes the GitHub URL.

## 8. Removing features is a major version
**Context.** 2.0 removes commands, MCP tools, settings and the `crossvet-chat` program that 1.x documented as stable.
**Decision.** A major version, a [migration guide](MIGRATING.md), and a clear message for every removed command (`crossvet chat route` says it was removed and why, with exit code 1). Kept 1.x spellings (`crossvet chat start`, `crossvet chat mcp`) still work, and the log opens unchanged.
**Cost.** 1.x settings files are refused with a pointer to `crossvet init` rather than half-read.
