# Changelog

All notable changes to Crossvet. Versions follow [Semantic Versioning](https://semver.org/). Release notes for each version are in [docs/releases/](docs/releases/).

## [Unreleased]

## [1.1.0] - 2026-11-25

### Tested live
- The chat benchmark: six models (gpt-6-luna, claude-haiku-5-5, gpt-6.1-terra, claude-sonnet-5-5, gpt-6.1-sol, claude-opus-5-5), all 28 cases each, code answers run and checked, 168 calls, none failed, $0.48: [docs/benchmarks/2026-11-25/](docs/benchmarks/2026-11-25/README.md).

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
