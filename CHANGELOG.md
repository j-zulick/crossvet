# Changelog

All notable changes to Crossvet. Versions follow [Semantic Versioning](https://semver.org/). Release notes for each version are in [docs/releases/](docs/releases/).

## [Unreleased]

## [0.5.0] - 2026-11-24

### Added
- Post imports from folders and URL lists; per-post summary of what each claim would change; repeated claims merged and decided together; contradictions marked (design decision 38).

## [0.4.0] - 2026-11-24

### Added
- `crossvet chat sync`: ratings added in Langfuse count in tuning; `tune --sync`.
- `crossvet chat report`: cost per model, ratings per kind, proposals; optionally posted to Langfuse (design decision 37).

## [0.3.0] - 2026-11-24

### Changed
- Light base install (chat, scanner, demo); `research`, `langfuse` and `all` extras; clear messages when an extra is missing; light-install and newest-dependency checks in CI (design decision 36).

## [0.2.0] - 2026-11-24

### Added
- `crossvet chat start`: config, key check, Hermes and Cursor settings, and the server in one step.
- Streamed answers in the server, `crossvet chat` and `crossvet chat ask`; fallback to the next model only before the first piece of text (design decision 35).

## [0.1.1] - 2026-11-24

### Fixed
- Fresh installs from GitHub picked up `mcp` 2.x, which broke `crossvet mcp`, `crossvet chat mcp` and research runs; `mcp` is capped below 2.

### Changed
- Dependency updates (GitHub Actions, Python, web UI); Dependabot opens one grouped pull request per kind a month. Details: [docs/releases/v0.1.1.md](docs/releases/v0.1.1.md).

## [0.1.0] - 2026-11-24

First release in this repository. Crossvet was designed and built from November 6 to 24, 2026 in a private repository, one tested version at a time; this release is the result. What it includes: [docs/releases/v0.1.0.md](docs/releases/v0.1.0.md).
