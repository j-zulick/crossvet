# Moving from Crossvet 1.x to 2.0

Crossvet 2.0 does one thing: you name a model, from any chat, and it answers. It no longer chooses, rates or compares models. Your log of past turns opens unchanged.

## What to do

1. Install 2.0: `uv tool install --force "git+https://github.com/j-zulick/crossvet@v2.0.1"`.
2. Write new settings: `crossvet init` (2.0 refuses a 1.x `crossvet-chat.toml` rather than half-read it). Move your keys to `~/.config/crossvet/.env` if you want `crossvet mcp` to find them from any folder; a `.env` in the folder you run from still works.
3. Rename environment variables: `CROSSVET_CHAT_CONFIG` → `CROSSVET_CONFIG`, `CROSSVET_CHAT_DB` → `CROSSVET_DB`, `CROSSVET_CHAT_TOKEN` → `CROSSVET_TOKEN`. `crossvet doctor` lists any 1.x names still set.
4. In Hermes or another OpenAI-style app, change the model from `auto` (or `crossvet/<slot>`) to a model name or `default`.
5. In Claude Code, Codex or Cursor: if the MCP entry runs `crossvet chat mcp`, it keeps working; `crossvet mcp` is the 2.0 spelling.
6. Run `crossvet doctor`.

## What changed

| 1.x | 2.0 |
|---|---|
| `model: auto`, `crossvet/<slot>`, `crossvet/<goal>` | A model name, a short name, or `default` |
| `crossvet chat start`, `serve`, `mcp`, `ask`, `log`, `init`, `doctor` | `crossvet start`, `serve`, `mcp`, `ask`, `log`, `init`, `doctor` (the 1.x spellings still work) |
| `crossvet chat` (terminal) | `crossvet chat`, with `--model` |
| `crossvet-chat` program | `crossvet` |
| 13 MCP tools | `list_models`, `ask_model`, `recent_turns` |
| `[slots]`, `[routes]`, `[router]`, `[kinds]`, `[inputs]`, `[privacy]`, `[memory]`, `[record]`, `[tuning]`, `[retention]` | `default_model`, `models`, `[names]`, `[prices]`, `[limits]`, `[store]` |
| A failed answer tried the next model in the slot | A failed call returns an error naming the model; you pick another |

## Removed

Routing of every kind (`auto`, kinds and difficulty, slots, goals, the routing table, input-based routing, private-to-local, cascade, escalation), `/why`, `/retry stronger`, `/good`, `/bad`, `/private`, answer checks, ratings and Langfuse recording, OpenTelemetry, the benchmark (`bench`), `route`, `routes`, `tune`, `learn`, `replay`, `export`, `report`, `dashboard`, `sync`, `compare`, `challenge`, `feedback`, `note`, `handoff`, `backup`, `restore`, `prune`, shared notes, the activity page (`/`, `/api/turns`, `/api/feedback`), prompt-cache markers, and the `langfuse`, `otel` extras. Each removed command prints what happened and exits with code 1.

The 1.x code and its benchmark results stay in the repository's history at tag `v1.1.1`.
