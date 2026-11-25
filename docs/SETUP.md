# Setup

## Install

Crossvet installs from GitHub (there is no PyPI package). With [uv](https://docs.astral.sh/uv/):

```bash
uv tool install "git+https://github.com/j-zulick/crossvet@v1.0.0"                # the chat (3 dependencies)
uv tool install "crossvet[langfuse] @ git+https://github.com/j-zulick/crossvet@v1.0.0"   # plus Langfuse recording
```

`pip install` takes the same strings in a virtual environment. Python 3.11 to 3.13.

## Keys

Make a folder for Crossvet (for example `~/crossvet-work`), copy [`.env.example`](../.env.example) there as `.env`, and fill in the keys you have. One provider is enough to start; more providers give the router more to choose from. `OPENROUTER_API_KEY` reaches most other vendors with one key. Crossvet reads `.env` from the folder you run it in and never prints a key.

## First run

```bash
cd ~/crossvet-work
crossvet chat start
```

`start` writes `crossvet-chat.toml` if there is none (filling the slots from the keys you have), checks the keys without calling a model, prints the settings to paste into Hermes and Cursor, and starts the server. Leave it running while you chat. `crossvet chat doctor` repeats the checks at any time.

## Hermes, Cursor and other chat apps

See [CHAT.md, Use it from other apps](CHAT.md#use-it-from-other-apps): a custom OpenAI-compatible provider at `http://127.0.0.1:8787/v1` with the model `auto` for Hermes and any chat app that takes an OpenAI URL, and the MCP server for Cursor, Claude Code and Codex.

## From a clone

```bash
git clone https://github.com/j-zulick/crossvet && cd crossvet
uv sync --all-extras
uv run pytest tests/unit -q      # offline tests
uv run pytest tests/live -q      # real API calls with the keys in .env (a few cents)
```

## If something doesn't work

- `crossvet chat doctor` names any key that is missing or any slot no key can reach.
- A provider that rejects your key, or reports a billing or quota problem, is skipped until you restart; `/why` and the answer line show which model answered.
- The server listens on this machine only. Listening on another address needs `CROSSVET_CHAT_TOKEN` (at least 16 characters).
