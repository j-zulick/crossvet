# What stays stable

The interfaces below follow [Semantic Versioning](https://semver.org/): a change that breaks one of them waits for the next major version, and anything deprecated keeps working, with a warning, for at least one minor release first. A test (`tests/unit/test_stability_doc.py`) checks that each list below matches the code.

## Covered

**Commands.** The `crossvet` program, these subcommands and their documented options:

<!-- list:commands -->
`ask`, `backup`, `bench`, `challenge`, `chat`, `compare`, `cost`, `dashboard`, `doctor`, `export`, `handoff`, `init`, `leaderboard`, `log`, `mcp`, `models`, `note`, `notes`, `prune`, `rate`, `replay`, `report`, `restore`, `review`, `route`, `score`, `serve`, `start`, `sync`, `tune`, `why`
<!-- /list -->

The 1.x spellings `crossvet chat <subcommand>` keep working for each of them. Exit codes: 0 success; 1 a failure or problems found; 2 a usage error; 3 a spend cap, or a log written by a newer Crossvet.

**The server's HTTP API** (`crossvet serve`, `crossvet start`): these paths; the OpenAI chat-completions request and response shapes they accept and return; the model names `default`, `crossvet`, short names, `provider:model`, `auto`, `crossvet/<slot>` and `crossvet/<goal>`; the `/model`, `/models`, `/cost`, `/why`, `/good`, `/bad`, `/retry` and `/help` commands; the `crossvet` block added to each response (`model`, `served_by`, `cost`, `thread`, `turn`, `dropped` when a field was dropped, and `decision` when Crossvet chose the model); and the headers `x-crossvet-thread` and `x-crossvet-app`.

<!-- list:http -->
`/health`, `/v1/chat/completions`, `/v1/models`
<!-- /list -->

**The MCP tools** (`crossvet mcp`): their names and arguments. New optional arguments may be added in a minor release.

<!-- list:mcp-tools -->
`ask`, `ask_model`, `challenge`, `compare_models`, `explain_route`, `handoff_result`, `handoff_status`, `handoff_submit`, `leaderboard`, `list_models`, `load_context`, `rate_answer`, `recent_turns`, `review_diff`, `save_note`, `search_memory`
<!-- /list -->

**Settings.** Every environment variable in [`.env.example`](../.env.example) and every key in [`crossvet.example.toml`](../crossvet.example.toml), with its meaning and default.

**The log and the lab file.** A log written by any 1.x, 2.x or 3.x release opens in any later 3.x release; the lab file (decisions, ratings, notes, routes, handoffs) is kept apart from it and keyed by turn id. Turns stay append-only. A log written by a newer release is refused rather than opened.

## Not covered

- The built-in model table, its short names, prices, the built-in default and the built-in slots: they follow the vendors.
- Which model `auto` picks for a given request: the rules are tuned as models change. `crossvet route` always shows the current choice and why.
- The wording of messages, footers and command replies.
- The Python modules' internals. Import `crossvet` code only for tests and experiments.
