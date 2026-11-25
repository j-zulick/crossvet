# Security model

What Crossvet protects, how, and what it does not cover. Reporting a vulnerability: [SECURITY.md](../SECURITY.md).

Crossvet sits between your chat app and several vendors' APIs, holds your keys, and keeps a record of every turn. The main risks are a key leaking, a private request leaving your machine, someone else reaching the server, and text that tries to steer the model reading it.

| Threat | Defense | Where | Limits |
|---|---|---|---|
| Leaked keys | Keys only from the environment or a git-ignored `.env`; `doctor` and `start` report presence, never values; CI scans every commit for secrets (gitleaks) | `chat/cli.py`, `.gitignore`, `ci.yml` | A key pasted into a chat message is outside this |
| Someone else uses your server | The server listens on this machine by default; any other address needs `CROSSVET_CHAT_TOKEN` (16+ characters), sent only in the `Authorization` header; a wrong token waits a second | `chat/server.py` | The pause slows guessing one request at a time; use a random token |
| The MCP server is reached from the network | Stdio by default; `--http` listens only on 127.0.0.1, localhost or ::1 | `chat/mcp_server.py` | — |
| A private request leaves the machine | `--private`, `/private`, `x-crossvet-private` or the automatic check (keys, ID and card numbers, "confidential") keep a request on a local model; with no local model it is refused, and it is never sent to Langfuse | `chat/inputs.py`, `chat/hub.py` | The automatic check is a pattern match: it misses private text that names no pattern |
| A post imported into the routing table carries instructions for the model that reads it | Every post is split into visible and hidden parts and checked by patterns in code before any model reads it; a post with a finding is refused; a claim counts only if its quote appears verbatim in the post; only you accept a change to the table | `injection_check.py`, `chat/pages.py`, `chat/tuning.py` | Pattern matching misses paraphrased and split instructions |
| History is rewritten | The store refuses updates and deletes (triggers); `prune` builds a new store by copying, after a backup | `chat/memory.py`, `chat/storage.py` | Anyone with write access to the file can replace it |
| A refused account keeps costing money | A provider that answers 401, 402, or a quota or billing refusal is not called again until restart | `chat/hub.py` | Restart after fixing the account |
| Spend runs away | Daily and per-call caps stop a call before it is made | `[limits]`, `chat/hub.py` | Prices come from the model list; a wrong price makes the cap wrong |

## Not covered
- A wrong answer from an honest model: the guard checks the shape of an answer (empty, cut off, broken JSON), and Jev's answer check is optional.
- Compromise of a model vendor or of a dependency.
- Anything a chat app does with the answers it receives.
