# Working on Crossvet

Instructions for coding agents (Claude Code, Codex, Cursor) and for people. `CLAUDE.md` points here.

## What this repository is
Crossvet is one chat that controls Claude, ChatGPT and other models. You use it from Hermes, Cursor or any chat app that speaks the OpenAI API or MCP, and it sends each request to a suitable model with the reason shown. Every outcome-deciding step (which kind of task, which model, whether an answer passed its check, whether a spend cap stops a call) is code, not a model's judgment.

**Scope rule:** a change belongs here only if it serves "one chat controls many models". Anything else is out of scope.

## Layout
- `src/crossvet/cli.py`: the `crossvet` front door (`crossvet chat ...`)
- `src/crossvet/chat/`: the chat
  - `classify.py`, `routing.py`, `router.py`, `inputs.py`: what kind of task a request is, which models to try and why, routers (rules, Jev, OpenRouter), routing by what a request carries
  - `hub.py`: route, guard the call (answer checks, escalation, spend caps, refused accounts), save the turn
  - `providers.py`: OpenAI, Anthropic, Google, xAI, OpenRouter, Ollama and any OpenAI-compatible server through one function
  - `server.py`: the OpenAI-compatible server for Hermes and other chat apps; `mcp_server.py`: MCP tools for Cursor, Claude Code and Codex
  - `memory.py`, `migrations.py`, `storage.py`: the chat store (one SQLite file), its upgrades, backup and restore
  - `record.py`, `langfuse_sync.py`, `report.py`: recording turns and ratings locally and in Langfuse, rating sync, the weekly report
  - `tuning.py`, `pages.py`, `learned.py`, `bench.py`: the routing table you tune (with posts checked for prompt injection), the learned router, and the chat benchmark
  - `council.py`, `handoff.py`, `replay.py`, `dashboard.py`, `setup.py`, `config.py`, `cli.py`
- `src/crossvet/injection_check.py`: the prompt-injection patterns used on imported posts
- `tests/unit/`: offline tests (no keys, no network); `tests/live/`: real API calls, skipped without keys
- `docs/`: `CHAT.md` (the guide), `SETUP.md`, `ARCHITECTURE.md`, `SECURITY-MODEL.md`, `DESIGN-DECISIONS.md`, `STABILITY.md`, `live-runs/` (dated real runs), `releases/`

## Commands
```bash
uv sync --all-extras             # install
uv run pytest tests/unit -q      # offline tests: must pass before any commit
uvx ruff@0.17.4 check src tests  # lint
uv run pytest tests/live -q      # live tests: real API calls with the keys in .env (a few cents)
uv run crossvet chat doctor      # check a configuration without spending tokens
```

## Rules
- Never read, print or commit `.env` or any key. `.env.example` lists every setting with an empty value.
- A claim in the README, a release note or a doc must match the code and the tests in the same commit. Results are published only from real runs, with date, model ids and cost (`docs/live-runs/`). No made-up examples in anything published.
- Checks that decide outcomes stay in code.
- A new design choice gets an entry in `docs/DESIGN-DECISIONS.md` (context, decision, cost).
- New setting: add it to `.env.example` or `crossvet-chat.example.toml`, document it in `docs/CHAT.md`, and test it. `docs/STABILITY.md` lists what stays compatible across 1.x; a test checks it.
- Model names go stale. Defaults come from a dated benchmark run; don't change one without new results.
