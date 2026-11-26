# Contributing to Crossvet

Thanks for your interest. Crossvet is a small project; issues and focused pull requests are welcome.

## Before you start
- For anything larger than a fix, open an issue first so we can agree on the approach.
- Read [AGENTS.md](AGENTS.md): the layout, the commands and the rules every change follows. It applies to people and coding agents alike.

## Set up and test
```bash
uv sync --all-extras
uv run pytest tests/unit -q      # offline: no API keys, no network
uvx ruff@0.17.4 check src tests
CROSSVET_LIVE=1 uv run pytest tests/live -q -rs   # real API calls with your keys (about $0.05)
```

## Rules that keep Crossvet honest
- **A named model is never switched.** Crossvet chooses only when a request names `auto`, a slot or a goal, and every choice is explained (`/why`) and recorded.
- **Guards stay in code:** spend caps, refused accounts, limits.
- **Claims match the code.** README text, release notes and docs change in the same pull request as the behavior they describe.
- **Results come only from real runs,** with the date, model ids and cost ([docs/live-runs/](docs/live-runs/)).
- **Design choices get an entry** in [docs/DESIGN-DECISIONS.md](docs/DESIGN-DECISIONS.md): context, decision, cost.
- **Never commit keys** or `.env` contents.

## Reporting security issues
Please follow [SECURITY.md](SECURITY.md) and report privately, not in a public issue.

## License
By contributing, you agree that your contribution is licensed under the [MIT License](LICENSE).
