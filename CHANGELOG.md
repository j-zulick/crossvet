# Changelog

All notable changes to Crossvet. Versions follow [Semantic Versioning](https://semver.org/). Release notes for each version are in [docs/releases/](docs/releases/).

## [Unreleased]

## [2.0.0] - 2026-11-26

Crossvet now does one thing: you name a model, from any chat, and that model answers. It no longer chooses, rates or compares models. Moving from 1.x: [docs/MIGRATING.md](docs/MIGRATING.md).

### Added
- `default_model`, short names (`[names]`) and a model menu (`models`), served at `/v1/models` so chat apps list them.
- `/model NAME`, `/model`, `/models`, `/cost` and `/help` in any OpenAI-style app; Crossvet leaves the commands and its replies out of what models see.
- Tool requests to OpenAI go through the Responses API, translated both ways: OpenAI's current models refuse tools on chat completions (found by the live run). Tool requests to Anthropic go through its OpenAI-compatible endpoint, so agents keep their tools with Claude too.
- Commands `crossvet start`, `chat --model`, `ask`, `models`, `cost`, `log`, `serve`, `mcp`, `init`, `doctor` (the 1.x `crossvet chat ...` spellings still work).
- A built-in table of six tested models with list prices dated 2026-11-26, used when there is no settings file.
- Keys are read from `~/.config/crossvet/.env` too, so `crossvet mcp` finds them from any folder.
- `docs/MIGRATING.md`; a live run: [docs/live-runs/2026-11-26.md](docs/live-runs/2026-11-26.md).

### Changed
- MCP tools: `list_models`, `ask_model(request, model, system)`, `recent_turns`. The answer from `ask_model` ends with its model, tokens and cost.
- A failed call returns an error that names the model; no other model is tried.
- Settings: `crossvet.toml` with `default_model`, `models`, `[names]`, `[prices]`, `[limits]`, `[store]`. Environment: `CROSSVET_CONFIG`, `CROSSVET_DB`, `CROSSVET_TOKEN`.
- The MCP Python SDK is locked at 2.3.0 (1.x still supported).

### Removed
- All routing (`auto`, kinds, difficulty, slots, goals, the routing table, input-based and private routing, cascade, escalation, answer checks), `/why`, `/retry`, `/good`, `/bad`, `/private`.
- Ratings, Langfuse and OpenTelemetry recording, the benchmark, tuning, the learned router, replay, export, report, dashboard, compare, challenge, handoffs, shared notes, backup, restore and prune; 18 commands in all (each now says it was removed), 10 MCP tools, the activity page, the `crossvet-chat` program, and the `langfuse` and `otel` extras. They remain in the history at tag `v1.1.1`.

## [1.1.1] - 2026-11-25

Repository presentation only; no change to how Crossvet behaves.

### Added
- `CODE_OF_CONDUCT.md` (Contributor Covenant 2.1), completing GitHub's community profile.
- A diagram of how a request is routed, and release, CodeQL, Python and license badges, in the README.

## [1.1.0] - 2026-11-25

### Tested live
- The chat benchmark: six models (gpt-6-luna, claude-haiku-5-5, gpt-6.1-terra, claude-sonnet-5-5, gpt-6.1-sol, claude-opus-5-5), all 28 cases each, code answers run and checked, 168 calls, none failed, $0.48: [docs/benchmarks/2026-11-25/](https://github.com/j-zulick/crossvet/blob/v1.1.0/docs/benchmarks/2026-11-25/README.md).

### Added
- Benchmark rows keep the first 600 characters of each answer (`answer`), so a low score can be checked against what the model said.

### Fixed (found by the live benchmark)
- `corrected-listing` asked for a "model" key with no year or make key, and all six models wrote "2016 Nissan Rogue". The case now asks for year, make and model separately.
- Names written with a typographic apostrophe (Scotti’s) did not match the answer key (Scotti's). Quote style is now ignored.
- `gold-certified` needed the digit 6, so "under six years old" lost a third of the score. Either spelling now counts.

## [1.0.0] - 2026-11-25

Crossvet is now one thing: one chat that controls Claude, ChatGPT and other models, used from Hermes, Cursor or any chat app. Everything else moved out (see Removed). Versions 0.2 to 0.9 were built but never published; their chat features are in this release.

### Tested live
- `tests/live/`: real API calls with the keys in `.env` (`CROSSVET_LIVE=1`), each on a task from used-car dealer work in Sarasota, Florida. The run of 2026-11-25 passed all 12 checks with OpenAI and Anthropic for an estimated $0.08: [docs/live-runs/2026-11-25.md](docs/live-runs/2026-11-25.md).

### Fixed (found by the live run)
- **OpenAI calls failed:** its current models refuse `max_tokens`. Crossvet sends `max_completion_tokens` to OpenAI and converts it in requests chat apps pass through.
- A challenge review cut off at the output limit now says so and names `[limits] max_output_tokens`, instead of a JSON error.
- `compare_models` results carry `cost_usd`, like every other tool (`cost` is kept).

### Added
- `crossvet chat start`: writes the settings file if there is none, checks your keys without calling a model, prints the Hermes, Cursor and Pi settings, and serves. Answers stream as they are written.
- Routing by what a request carries: images go to a `vision` slot, audio to `audio` (or is transcribed first), PDFs to `long`; pasted code makes a vague request a code task.
- Goals per request (`best`, `cheapest`, `fastest`), `[router] cascade`, `[router] local_first`, and `[kinds]` (models to try first per kind of task; `crossvet chat bench --apply` writes it).
- Private requests stay on your machine (`--private`, `/private`, `x-crossvet-private`, and automatic detection of keys, ID and card numbers and "confidential"); refused when no local model is set; never sent to Langfuse.
- A provider that refuses the account (401, 402, or a quota or billing refusal) is not called again until restart.
- Ratings added in Langfuse count in tuning (`crossvet chat sync`); a weekly report (`crossvet chat report`); `crossvet chat replay --experiment` runs routers as Langfuse experiments.
- `crossvet chat learn` and `[router] use = "learned"`: a router trained on your ratings that has to beat the rules on held-out answers (off until you switch it on).
- Post imports from folders and URL lists, with repeats merged and contradictions marked.
- `crossvet chat backup`, `restore`, `prune --older-than`; request time and size limits; `[retention] keep_days`.
- The chat store records its schema version and upgrades itself in place, saving a backup first.
- `crossvet chat dashboard` (one local HTML page); OpenTelemetry spans (`otel` extra); prompt caching for Anthropic.
- The chat runs on MCP Python SDK 1.x and 2.x.
- `LOCAL_LLM_BASE_URL` and `LOCAL_LLM_API_KEY`, earlier names for the local-model settings, are read as `LOCAL_BASE_URL` and `LOCAL_API_KEY`.

### Changed
- The Python package is `crossvet`; the commands are `crossvet` (with `crossvet chat ...`) and `crossvet-chat`.
- The base install has three dependencies: httpx, the MCP SDK and python-dotenv. Extras: `langfuse`, `otel`, `all`.

### Removed
- The research pipeline and cross-vendor review (`crossvet research`, `review`, `try`, `ask`), the prompt-injection scanner command (`crossvet scan`), the role benchmark (`crossvet-bench`), `compare`, `dataset`, `demo`, `setup`, `doctor`, the research MCP server, the LangGraph server and web UI, and their Docker files. They remain in the history of v0.1.1. The injection check itself stays: it guards post imports.

## [0.1.1] - 2026-11-24

### Fixed
- Fresh installs from GitHub picked up `mcp` 2.x, which broke `crossvet mcp`, `crossvet chat mcp` and research runs; `mcp` is capped below 2.

### Changed
- Dependency updates (GitHub Actions, Python, web UI); Dependabot opens one grouped pull request per kind a month. Details: [docs/releases/v0.1.1.md](docs/releases/v0.1.1.md).

## [0.1.0] - 2026-11-24

First release in this repository. Crossvet was designed and built from November 6 to 24, 2026 in a private repository, one tested version at a time; this release is the result. What it includes: [docs/releases/v0.1.0.md](docs/releases/v0.1.0.md).
