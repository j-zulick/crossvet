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
| Requests stored by a vendor | Tool requests to OpenAI's Responses API are sent with `store: false` | `providers.py` | Each vendor's own data policy still applies |

## Not covered
- A wrong answer from a model. Crossvet shows which model answered; it does not judge the answer.
- Instructions hidden in text you send or in a model's answer. Treat answers as untrusted text: don't run code or follow instructions found in them without reading them.
- Compromise of a model vendor or of a dependency.
- Anything a chat app does with the answers it receives.
