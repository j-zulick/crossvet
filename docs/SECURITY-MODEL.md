# Security model

What Crossvet protects, how, and what it does not cover. Reporting a vulnerability: [SECURITY.md](../SECURITY.md).

Crossvet sits between your chat apps and several vendors' APIs, holds your keys, and logs every turn. The main risks are a key leaking, someone else reaching the server, spend running away, and text that tries to steer a model.

| Threat | Defense | Where | Limits |
|---|---|---|---|
| Leaked keys | Keys only from the environment or a git-ignored `.env`; `doctor` and `start` report whether a key is set, never its value; CI scans every commit for secrets (gitleaks) | `config.py`, `cli.py`, `.gitignore`, `ci.yml` | A key pasted into a chat message is outside this |
| Someone else uses your server | It listens on this computer by default; any other address needs `CROSSVET_TOKEN` (16+ characters), accepted only in the `Authorization` header and compared in constant time; a wrong token waits a second | `server.py` | The pause slows guessing one request at a time; use a random token |
| The MCP server is reached from the network | Stdio by default; `--http` listens only on 127.0.0.1, localhost or ::1 | `mcp_server.py` | — |
| Spend runs away | Daily and per-call caps stop a call before it is made; one output limit and one timeout for every call; request size limit on the server | `core.py`, `[limits]` | A model with no price counts as $0 |
| A refused account keeps costing money | A provider that answers 401, 402, or a quota or billing refusal is not called again until restart | `core.py`, `providers.py` | Restart after fixing the account |
| History is rewritten | The log refuses updates and deletes (SQLite triggers) | `store.py` | Anyone with write access to the file can replace it |
| Requests stored by a vendor | Tool requests to OpenAI's Responses API are sent with `store: false` | `relay.py` | Each vendor's own data policy still applies |
| A private request reaches a cloud model through auto | Requests that look private (keys, card and ID numbers, "confidential", `[private]`) only go to the `private` slot; with none set they are refused before anything is sent | `routing.py` | A pattern match: it misses some private text; a model you name yourself is not checked |
| A model talks its way into a verdict | Challenge, replay and judge verdicts are JSON with fixed values, read in code; the question and answers are fenced and marked as data; judges are blind to authorship | `multi.py` | A judge can still be wrong |
| A handoff changes your files or runs a shell | The agent CLI is run without a shell, with the task as one argument, in the folder you name, with its own non-approving defaults (Claude Code print mode, Codex read-only sandbox), under a time limit | `handoff.py` | An agent you have configured to auto-approve edits will use that configuration |
| A review changes your working tree | A fix is only a patch until you pass `--apply`; it must pass `git apply --check` first; git runs without a shell, and a `--base` name must look like a branch, tag or commit | `review.py` | An applied patch is real code a model wrote: read it before you commit |
| Benchmark code runs on your machine | Code answers are only read (parsed) unless you pass `--run-code`; then they run in a separate, isolated Python process with a time limit | `bench.py` | It is still code a model wrote: run it only where that is acceptable |
| Kept reasoning | OpenAI's reasoning for tool calls is kept only as the encrypted blob OpenAI returns, in the local log's `relay_state` table, for 7 days, and only sent back to the same model | `store.py`, `relay.py` | Anyone with the log file has the blobs (they are encrypted by OpenAI, not readable as text) |

## Not covered
- A wrong answer from a model. Crossvet shows which model answered, and `challenge` can have another vendor check it, but nothing guarantees an answer is right.
- Instructions hidden in text you send or in a model's answer. Treat answers as untrusted text: don't run code or follow instructions found in them without reading them.
- Compromise of a model vendor or of a dependency.
- Anything a chat app does with the answers it receives.
