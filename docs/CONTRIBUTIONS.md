# Contributions and AI assistance

## Who did what

**Joseph Zulick (author, maintainer)**
- Chose the problem and the design: cross-vendor review of research reports, with outcomes decided by checks in code rather than by a model's say-so.
- Set the scope of every release and picked which ideas to adopt from other projects and papers (see the Credits section of the README and `NOTICES.md`), and which to leave out.
- Chose the integrations (LangGraph, Deep Agents, Langfuse, OpenRouter, Jev, MCP, self-hosted models) and the domain packs, which come from his SEO/GEO and marketing consulting work.
- Reviewed and approved every change before it was merged, and decides what gets published and deployed.
- The live example run and the first role benchmark were paid for with his API keys.

**Claude (Anthropic), through Claude Code**
- Wrote most of the code, tests and documentation in this fork under his direction, ran the test suite and audits, and drafted release notes.
- This repository starts from a single commit of v0.1.0, built in a private repository. That commit and later ones it helped with carry a `Co-Authored-By: Claude` trailer.

**Upstream**
- Everything under LangChain's Open Deep Research and Agent Chat UI (both MIT) is their work. Upstream's legacy implementations (`src/legacy/`) and its Deep Research Bench scripts, results and original README are not included, because Crossvet never used them; they remain in the upstream repository.

## How AI-written work is checked
- The offline test suite (`uv run pytest tests/unit -q`) must pass for every release, from a fresh checkout.
- Claims in the README and release notes are checked against the code and tests of that release. Measured results are published only from real runs, with date, model ids and cost, and comparisons that haven't been run are listed as "not run" (`docs/EVALS.md`).
- CI runs CodeQL, gitleaks and an SBOM build; keys never leave `.env`.
- Outcome-deciding checks (citations, verbatim quotes, stop rules, support thresholds) are deterministic code with unit tests, so they don't depend on a model behaving.
