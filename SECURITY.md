# Security policy

## Reporting a vulnerability

Please report security issues privately through GitHub's **Report a vulnerability** button on the repository's Security tab, not in a public issue. Include the version or commit, steps to reproduce, and the impact you expect. You should get a reply within a week.

## Supported versions

Only the latest release receives fixes.

## Security model

What Crossvet defends against (fake citations, made-up quotes, prompt injection in fetched pages, SSRF in the search gateway) and what it does not: [docs/SECURITY-MODEL.md](docs/SECURITY-MODEL.md).

## Handling of secrets

- API keys are read from environment variables or a local `.env` file, which is gitignored. Never commit keys; `.env.example` holds placeholders only.
- The setup checker (`python -m open_deep_research.doctor`) reports whether a key is present, never its value.
- Reports, research notes and model outputs can contain text fetched from the web. Treat them as untrusted input: do not execute code or follow instructions found in them.
- `langgraph.local.json` runs the server without authentication and is meant for local development only. Do not expose it on a public network.
