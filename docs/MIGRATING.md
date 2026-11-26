# Moving to Crossvet 3

## From 2.x

Nothing you use changes. A model you name answers exactly as before, every command, MCP tool, setting and environment variable keeps working, and your log opens unchanged. What 3.0 adds is opt-in:

1. Install: `uv tool install --force "git+https://github.com/j-zulick/crossvet@v3.4.0"`.
2. Optional: name `auto` (or `crossvet/strong`, `crossvet/cheapest`...) where you want Crossvet to choose. `crossvet route "your request"` shows what it would pick, and why.
3. Optional: run `crossvet init --force` to write a settings file with the new `[slots]` and `[router]` sections, or copy them from [crossvet.example.toml](../crossvet.example.toml). Without them, the slots are filled from the built-in table with the models your keys can call.
4. Optional: add a model on your machine to `[slots] private` so requests that look private can go to `auto` too. Without one, such requests are refused under `auto` (never sent to a cloud model).

New next to your log: `lab.db` (decisions, ratings, notes, accepted routes, handoffs). `crossvet backup` copies both files.

| 2.x | 3.0 |
|---|---|
| A model name, a short name, or `default` | The same, plus `auto`, `crossvet/<slot>`, `crossvet/<goal>` |
| `/model`, `/models`, `/cost`, `/help` | The same, plus `/why`, `/good`, `/bad`, `/retry [stronger]` |
| 3 MCP tools | The same 3, plus `ask`, `explain_route`, `compare_models`, `challenge`, `rate_answer`, `save_note`, `search_memory`, `load_context`, `handoff_submit`, `handoff_status`, `handoff_result` |
| `default_model`, `models`, `[names]`, `[prices]`, `[limits]`, `[store]` | The same, plus `[slots]`, `[routes]`, `[router]`, `[lab]`, `[score]` (off by default) |
| `crossvet chat route` etc. printed "removed" | `route`, `bench`, `compare`, `challenge`, `note`, `tune`, `replay`, `report`, `dashboard`, `export`, `sync`, `handoff`, `backup`, `restore` and `prune` work, as `crossvet <command>` or `crossvet chat <command>` |

## From 1.x

1. Install 3.0 as above.
2. Settings: 1.x `[slots]` (lists of models) and `[routes]` read as before. Remove the 1.x sections 3.0 does not have (`[kinds]`, `[inputs]`, `[privacy]`, `[memory]`, `[record]`, `[tuning]`, `[retention]`) or run `crossvet init` for a fresh file; an unknown section is refused with its name. Move 1.x `[privacy] models` to `[slots] private`, and `[router] goal` stays `[router] goal`.
3. Rename environment variables: `CROSSVET_CHAT_CONFIG` → `CROSSVET_CONFIG`, `CROSSVET_CHAT_DB` → `CROSSVET_DB`, `CROSSVET_CHAT_TOKEN` → `CROSSVET_TOKEN`. `crossvet doctor` lists any 1.x names still set.
4. The `crossvet-chat` program is `crossvet`. `crossvet chat routes` is now `crossvet tune`, `feedback` is `rate`.
5. Ratings and notes from 1.x were kept in the 1.x tables of the log; 3.0 starts its lab file empty. Your turns carry over.
6. Run `crossvet doctor`.
