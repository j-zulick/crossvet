# Using Crossvet

One chat, any model. You name the model; Crossvet calls that vendor's API, shows what it cost, and logs the turn. It never chooses a model for you.

- [Naming a model](#naming-a-model)
- [Hermes and other OpenAI-style apps](#hermes-and-other-openai-style-apps)
- [Claude Code, Codex and Cursor (MCP)](#claude-code-codex-and-cursor-mcp)
- [The terminal](#the-terminal)
- [Agents and tools](#agents-and-tools)
- [Costs and caps](#costs-and-caps)
- [The local log](#the-local-log)
- [Settings](#settings)
- [Commands](#commands)

## Naming a model

| You write | Crossvet calls |
|---|---|
| `anthropic:claude-opus-5-5`, `openai:gpt-6.1-sol` | that model, from that vendor's API |
| `google:<model>`, `xai:<model>` | Google's or xAI's OpenAI-compatible API |
| `openrouter:<vendor>/<model>` | that model through OpenRouter (one key for most vendors; real cost reported) |
| `ollama:<model>`, `local:<model>` | a model on your own machine (`OLLAMA_BASE_URL`, `LOCAL_BASE_URL`) |
| a short name (`opus`, `sonnet`, `haiku`, `sol`, `terra`, `luna`, `claude`, `gpt`) | the model it stands for in your settings |
| nothing, `default` or `crossvet` | your `default_model` |

`crossvet models` lists your models, their short names, their prices and the default. Any `provider:model` works even if it is not listed. An unknown name is refused with the list of short names; nothing is guessed.

## Hermes and other OpenAI-style apps

Run `crossvet start` and leave it running. It prints:

```
base URL   http://127.0.0.1:8787/v1
API key    any text (not checked on this computer)
model      default, or any name from `crossvet models`
```

In Hermes, set a custom provider in `~/.hermes/config.yaml`:

```yaml
model:
  provider: custom
  base_url: http://127.0.0.1:8787/v1
  default: default
```

Any app that takes an OpenAI base URL (Open WebUI, LibreChat, your own code with the OpenAI SDK) connects the same way.

Which model answers is decided by the request:

1. the latest `/model NAME` typed in the conversation;
2. else the request's `model` field (the app's model menu, filled from Crossvet's `/v1/models`);
3. `default` means your `default_model`.

Typed as the whole message, these work in any app and call no model. Crossvet leaves them, and its replies to them, out of what models see:

| Command | What it does |
|---|---|
| `/model NAME` | Use NAME for the rest of this conversation |
| `/model` | Show the model in use |
| `/models` | List your models |
| `/cost` | Spend in this conversation, per model, and today |
| `/help` | This list |

Each response carries a `crossvet` block with the model, the cost, the conversation id and the turn id. Send `x-crossvet-thread` to set the conversation id yourself, and `x-crossvet-app` to name the app in the log.

## Claude Code, Codex and Cursor (MCP)

```bash
claude mcp add --scope user crossvet -- crossvet mcp     # Claude Code, every project
codex mcp add crossvet -- crossvet mcp                   # Codex
```

Cursor: `crossvet start --no-serve` prints the entry for `~/.cursor/mcp.json`, with the full path to `crossvet` so Cursor finds it.

| Tool | What it does |
|---|---|
| `list_models` | Your models, short names, prices and the default |
| `ask_model(request, model="default", system="")` | Ask one model. The answer ends with a line naming the model, tokens and cost |
| `recent_turns(limit=10)` | The latest questions and answers from every app |

Ask in plain words: "use ask_model with sol to review this function", "ask opus and luna the same question and show both answers". The model you ask does not see your conversation, so include what it needs in `request`. `crossvet mcp --http` serves the same tools over Streamable HTTP on 127.0.0.1:8788.

## The terminal

```bash
crossvet chat --model opus          # chat; /model NAME switches, /models, /cost, /new, /quit
crossvet ask -m sol "Is 48,000 miles high for a 2019 CR-V?"
git diff | crossvet ask -m sonnet -s "Review this diff for bugs."
```

Answers stream as they arrive, followed by one line: model, tokens in and out, cost, seconds.

## Agents and tools

Hermes and other agents send `tools` and tool results. Crossvet passes the whole request to the model you named and returns its tool calls unchanged:

- OpenAI-style providers get the request as it is.
- Anthropic models get it through Anthropic's OpenAI-compatible endpoint.
- OpenAI models get it through OpenAI's Responses API. On 2026-11-26, gpt-6.1-sol, gpt-6.1-terra and gpt-6-luna all refused tools on chat completions; Crossvet translates the request and the reply, so your app still speaks chat completions.

A tool request is answered in one piece, then streamed to the app if it asked for a stream. Text-only requests stream as the model writes.

## Costs and caps

- **Cost of each answer:** the vendor's list price times the tokens (`[prices]`, with a built-in table for the models this project tests, dated in `config.py`), or the cost OpenRouter reports. A model with no price shows "price unknown" and counts as $0 for the daily cap; `crossvet doctor` lists such models.
- **Daily cap** (`max_usd_per_day`, default $5): once today's logged spend reaches it, calls stop until midnight.
- **Per-call cap** (`max_usd_per_call`, default $0.50): before each call, the worst case (the request's size plus the full output limit) is priced; a call that could pass the cap is refused before it is made.
- **Refused keys:** a provider that answers 401, 402, or a quota or billing refusal is not called again until you restart Crossvet.
- **Limits:** `max_output_tokens` (4,000), `timeout_seconds` (120) for every call, and `max_request_bytes` (2 MB) for the server.

Nothing is retried and no other model is tried. A failed call returns an error that names the model, so you can pick another.

## The local log

Every question and answer goes to one SQLite file (`~/.local/share/crossvet/chat.db`, or `CROSSVET_DB`): app, model, tokens, cost, seconds. Turns can't be changed or deleted (SQLite triggers refuse it). The server, the MCP server and the terminal share it, so `crossvet log`, `crossvet cost` and the `recent_turns` tool see every app. It is the same file and table as Crossvet 1.x.

## Settings

Without a settings file, Crossvet uses the models in its built-in table that your keys can call, with short names, and Claude Sonnet 5.5 (or GPT-6.1 Terra) as the default. `crossvet init` writes that as a file you can edit: `~/.config/crossvet/crossvet.toml`, or `./crossvet.toml`, or the path in `CROSSVET_CONFIG`. Example: [crossvet.example.toml](../crossvet.example.toml).

```toml
default_model = "sonnet"
models = ["anthropic:claude-opus-5-5", "anthropic:claude-sonnet-5-5", "openai:gpt-6.1-sol", "openai:gpt-6-luna"]

[names]
opus = "anthropic:claude-opus-5-5"
sonnet = "anthropic:claude-sonnet-5-5"
sol = "openai:gpt-6.1-sol"
luna = "openai:gpt-6-luna"

# A price (USD per million tokens) for a model that is not in the built-in table:
# [prices."openrouter:vendor/model"]
# input = 1.0
# output = 5.0

[limits]
max_usd_per_day = 5.0
max_usd_per_call = 0.50
max_output_tokens = 4000
timeout_seconds = 120
max_request_bytes = 2000000
```

Keys come from the environment, `./.env` or `~/.config/crossvet/.env` (the environment wins). [`.env.example`](../.env.example) lists every one.

## Commands

| Command | What it does |
|---|---|
| `crossvet start [--no-serve]` | Check keys, print the settings for each app, serve on 127.0.0.1:8787 |
| `crossvet chat [-m MODEL]` | Chat in this terminal |
| `crossvet ask [-m MODEL] [-s SYSTEM] TEXT` | One question; reads standard input when no text is given |
| `crossvet models` | Your models, short names, prices, the default |
| `crossvet cost [--days N]` | Spend per model |
| `crossvet log [-n N]` | The latest turns from every app |
| `crossvet serve [--host --port]` | The OpenAI-compatible server only |
| `crossvet mcp [--http]` | The MCP server |
| `crossvet init [--path P] [--force]` | Write a settings file from your keys |
| `crossvet doctor` | Check keys, settings and the log; never calls a model |

Exit codes: 0 success; 1 a failure or problems found; 2 a usage error; 3 a spend cap or a log written by a newer Crossvet.
