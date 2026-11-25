# What stays stable

From 1.0 on, the interfaces below follow [Semantic Versioning](https://semver.org/): a change that breaks one of them waits for 2.0, and anything deprecated keeps working, with a warning, for at least one minor release first. A test (`tests/unit/chat/test_stability_doc.py`) checks that each list below matches the code.

## Covered

**The Python package** `crossvet`: the modules and functions documented in `docs/`.

**Commands.** These programs, their subcommands and their documented options:

<!-- list:scripts -->
`crossvet`, `crossvet-chat`
<!-- /list -->

`crossvet chat` (the same as `crossvet-chat`) has these subcommands:

<!-- list:chat-commands -->
`ask`, `backup`, `bench`, `challenge`, `chat`, `compare`, `dashboard`, `doctor`, `export`, `feedback`, `handoff`, `init`, `learn`, `log`, `mcp`, `note`, `prune`, `replay`, `report`, `restore`, `route`, `routes`, `serve`, `start`, `sync`, `tune`
<!-- /list -->

Exit codes: 0 for success, 1 for a failure or problems found, 2 for a usage error or a step that needs `--yes`.

**The chat server's HTTP API** (`crossvet chat serve`): these paths, the OpenAI chat-completions request and response shapes they accept and return, the model names `auto`, `crossvet/<slot>`, `crossvet/<goal>` and `provider:model`, the `crossvet` block added to each response, and the headers `x-crossvet-thread`, `x-crossvet-app`, `x-crossvet-router`, `x-crossvet-goal` and `x-crossvet-private`.

<!-- list:http -->
`/`, `/api/feedback`, `/api/turns`, `/health`, `/v1/chat/completions`, `/v1/models`
<!-- /list -->

**The chat's MCP tools** (`crossvet chat mcp`): their names and arguments. New optional arguments and new fields in results may be added in a minor release.

<!-- list:mcp-tools -->
`ask`, `ask_model`, `challenge`, `compare_models`, `explain_route`, `handoff_result`, `handoff_status`, `handoff_submit`, `load_context`, `rate_answer`, `recent_turns`, `save_note`, `search_memory`
<!-- /list -->

**Settings.** Every environment variable in [`.env.example`](../.env.example) and every section and key in [`crossvet-chat.example.toml`](../crossvet-chat.example.toml), with its meaning and default. A setting is renamed only with the old name still read, and a warning, for at least one minor release.

**The chat store.** From 1.0, a store made by any 1.x release opens in any later 1.x release, and `crossvet chat backup` copies restore across them. Turns, ratings and notes stay append-only. The store records its schema version; a newer release upgrades it in place when it opens it, saving a backup first (`chat.before-upgrade-v<N>.db`), and a store made by a newer release is refused rather than opened. Each schema change ships as a new step with a test that opens a store made before it (`chat/migrations.py`).

## Not covered

- Prompts, the wording of answers, reasons and Review notes, and the order of findings.
- Default model ids and prices: they come from dated benchmark runs and change when the results do.
- Benchmark cases and their scores. A new case changes a suite's totals; results are compared only within one run.
- The activity page's look.
- Output files' column order. Columns are read by name.
