# What stays stable

From 2.0 on, the interfaces below follow [Semantic Versioning](https://semver.org/): a change that breaks one of them waits for 3.0, and anything deprecated keeps working, with a warning, for at least one minor release first. A test (`tests/unit/test_stability_doc.py`) checks that each list below matches the code.

## Covered

**Commands.** The `crossvet` program, these subcommands and their documented options:

<!-- list:commands -->
`ask`, `chat`, `cost`, `doctor`, `init`, `log`, `mcp`, `models`, `serve`, `start`
<!-- /list -->

The 1.x spellings `crossvet chat <subcommand>` keep working for each of them. Exit codes: 0 success; 1 a failure or problems found; 2 a usage error; 3 a spend cap, or a log written by a newer Crossvet.

**The server's HTTP API** (`crossvet serve`, `crossvet start`): these paths; the OpenAI chat-completions request and response shapes they accept and return; the model names `default`, `crossvet`, short names and `provider:model`; the `/model`, `/models`, `/cost` and `/help` commands; the `crossvet` block added to each response; and the headers `x-crossvet-thread` and `x-crossvet-app`.

<!-- list:http -->
`/health`, `/v1/chat/completions`, `/v1/models`
<!-- /list -->

**The MCP tools** (`crossvet mcp`): their names and arguments. New optional arguments may be added in a minor release.

<!-- list:mcp-tools -->
`ask_model`, `list_models`, `recent_turns`
<!-- /list -->

**Settings.** Every environment variable in [`.env.example`](../.env.example) and every key in [`crossvet.example.toml`](../crossvet.example.toml), with its meaning and default.

**The log.** A log written by any 1.x or 2.x release opens in any later 2.x release. Turns stay append-only. A log written by a newer release is refused rather than opened.

## Not covered

- The built-in model table, its short names, prices and the built-in default: they follow the vendors.
- The wording of messages, footers and command replies.
- The Python modules' internals. Import `crossvet` code only for tests and experiments.
