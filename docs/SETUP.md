# Setup

## Install

Crossvet installs from GitHub (there is no PyPI package). With [uv](https://docs.astral.sh/uv/):

```bash
uv tool install "git+https://github.com/j-zulick/crossvet@v3.2.0"
```

`pip install "git+https://github.com/j-zulick/crossvet@v3.2.0"` works in a virtual environment too. Python 3.11 to 3.13. Three dependencies: httpx, the MCP Python SDK (1.x or 2.x) and python-dotenv.

## Keys

Put the keys you have in `~/.config/crossvet/.env` (copy [`.env.example`](../.env.example)), or export them in your shell. One provider is enough. Crossvet reads `./.env` first, then `~/.config/crossvet/.env`; a variable already set in the environment wins. Keeping them in `~/.config/crossvet/.env` means `crossvet mcp` finds them whichever folder an app starts it in. Crossvet never prints a key.

## First run

```bash
crossvet start
```

It checks which keys are set (without calling a model), prints the settings for Hermes, Claude Code, Codex and Cursor, and starts the server. Leave it running while you chat from Hermes or another OpenAI-style app; the MCP apps start `crossvet mcp` themselves. `crossvet doctor` repeats the checks at any time. `crossvet init` writes the settings to a file you can edit ([Settings](CHAT.md#settings)).

## Connect your apps

See [Using Crossvet](CHAT.md): Hermes and other OpenAI-style apps, then Claude Code, Codex and Cursor.

## From a clone

```bash
git clone https://github.com/j-zulick/crossvet && cd crossvet
uv sync --all-extras
uv run pytest tests/unit -q                       # offline: no keys, no network
CROSSVET_LIVE=1 uv run pytest tests/live -q -rs   # real API calls with your keys (about $0.05)
```

## If something doesn't work

- `crossvet doctor` names each key that is set or missing, any listed model no key can reach, and any model without a price.
- "unknown model": write `provider:model`, or a short name from `crossvet models`.
- A provider that rejected your key or reported a billing or quota problem is not called again until you restart Crossvet.
- The server listens on this computer only. Another address needs `CROSSVET_TOKEN` (at least 16 characters), sent as `Authorization: Bearer <token>`.
- `auto` refuses a request that looks private when no `private` slot is set: add a local model to `[slots] private`, remove the private details, or name a model.
- Coming from 2.x or 1.x: [MIGRATING.md](MIGRATING.md).
