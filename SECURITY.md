# Security policy

## Reporting a vulnerability

Please report security issues privately through GitHub's **Report a vulnerability** button on the repository's Security tab, not in a public issue. Include the version, steps to reproduce, and the impact you expect. You should get a reply within a week.

## Supported versions

Only the latest release receives fixes.

## Security model

What Crossvet protects (your keys, the local server, your spend and the log) and what it does not: [docs/SECURITY-MODEL.md](docs/SECURITY-MODEL.md).

## Handling of secrets

- API keys are read from environment variables or a local `.env` file, which is git-ignored. Never commit keys; `.env.example` holds placeholders only.
- `crossvet doctor` and `crossvet start` report whether a key is present, never its value.
- Answers are untrusted text: do not run code or follow instructions found in them without reading them.
