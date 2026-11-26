# Working on Crossvet

Instructions for coding agents (Claude Code, Codex, Cursor) and for people. `CLAUDE.md` points here.

## What this repository is
Crossvet is one chat, any model: you use Claude, ChatGPT, Gemini, Grok or a local model from Hermes, Cursor, Claude Code, Codex or a terminal, and you name the model. It never chooses a model for you.

**Scope rule:** a change belongs here only if it serves "name any model, from the chat you already use". Anything that chooses, routes, rates, scores or compares models is out of scope for this repository.

## Layout
- `src/crossvet/core.py`: the one path every request takes: resolve the name, check the caps, call, log
- `src/crossvet/providers.py`: every vendor through one function; tool requests passed through (Anthropic's OpenAI-compatible endpoint, OpenAI's Responses API)
- `src/crossvet/server.py`: the OpenAI-compatible server; `src/crossvet/mcp_server.py`: three MCP tools
- `src/crossvet/config.py`: default model, short names, menu, prices (a dated built-in table), limits, `.env` loading
- `src/crossvet/store.py`: the local log (SQLite, append-only)
- `src/crossvet/cli.py`: the `crossvet` command
- `tests/unit/`: offline tests (no keys, no network); `tests/live/`: real API calls, skipped unless `CROSSVET_LIVE=1`
- `docs/`: `CHAT.md` (the guide), `SETUP.md`, `ARCHITECTURE.md`, `DESIGN-DECISIONS.md`, `SECURITY-MODEL.md`, `STABILITY.md`, `MIGRATING.md`, `live-runs/` (dated real runs), `releases/`

## Commands
```bash
uv sync --all-extras                               # install
uv run pytest tests/unit -q                        # offline tests: must pass before any commit
uvx ruff@0.17.4 check src tests                    # lint
CROSSVET_LIVE=1 uv run pytest tests/live -q -rs    # real API calls with your keys (about $0.02)
uv run crossvet doctor                             # check keys and settings without calling a model
```

## Rules
- Never read, print or commit `.env` or any key. `.env.example` lists every variable with an empty value.
- A claim in the README, a release note or a doc must match the code and the tests in the same commit. Results are published only from real runs, with date, model ids and cost (`docs/live-runs/`). No made-up examples.
- Guards that decide outcomes (caps, refused accounts, limits) stay in code.
- A new design choice gets an entry in `docs/DESIGN-DECISIONS.md` (context, decision, cost).
- A new setting goes in `.env.example` or `crossvet.example.toml`, in `docs/CHAT.md`, and in a test. `docs/STABILITY.md` lists what stays compatible across 2.x; a test checks it.
- The built-in model table (`config.KNOWN`) changes only with a live run of the new model and its list price, dated.
