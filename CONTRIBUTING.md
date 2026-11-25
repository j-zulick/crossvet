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
uv run pytest tests/live -q      # real API calls; needs keys in .env and costs a few cents
```

## Rules that keep Crossvet honest
- **Checks that decide outcomes stay in code:** routing rules, answer checks, spend caps. Don't replace them with a model's judgment.
- **Claims match the code.** README text, release notes and docs change in the same pull request as the behavior they describe.
- **Results come only from real runs,** with the date, model ids and cost ([docs/live-runs/](docs/live-runs/)).
- **Design choices get an entry** in [docs/DESIGN-DECISIONS.md](docs/DESIGN-DECISIONS.md): context, decision, cost.
- **Never commit keys** or `.env` contents.

## Reporting security issues
Please follow [SECURITY.md](SECURITY.md) and report privately, not in a public issue.

## License
By contributing, you agree that your contribution is licensed under the [MIT License](LICENSE).
