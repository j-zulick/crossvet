# Crossvet

[![CI](https://github.com/j-zulick/crossvet/actions/workflows/ci.yml/badge.svg)](https://github.com/j-zulick/crossvet/actions/workflows/ci.yml) [![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE) [![Python 3.11–3.13](https://img.shields.io/badge/python-3.11%E2%80%933.13-blue.svg)](.python-version)

**Deep research whose reports are checked by models from several AI vendors before you see them.**

Crossvet extends LangChain's [Open Deep Research](https://github.com/langchain-ai/open_deep_research) (MIT). A single model writing a research report will state unsupported claims with confidence. Crossvet adds a **cross-vendor review** stage: after the draft report is written,

1. reviewers from different vendors (e.g. OpenAI, Anthropic, Google, or a self-hosted model) critique it **independently and in parallel**, as typed objects;
2. the critiques are **anonymized and shuffled**, and every reviewer ranks them — combined with a **confidence-weighted Borda count**;
3. a **deterministic citation check** flags any URL the report cites that never appeared in the research notes;
4. an **independent critic** (always a different model from the finding's author) checks every reviewer finding against the research notes: *agree*, *disagree with evidence* (an exact quote, verified in code before it can overrule anything), or *disagree concern*. Contradicted findings are dropped; unresolved ones go to a **Disputed** section for a human;
5. optionally, reviewers **deliberate** for up to three rounds (`REVIEW_DELIBERATION_ROUNDS`): a rotating challenger contests findings and the author holds, revises or withdraws them. A change of position counts only with a passage from the research notes, verified in code; changes without one are ignored and flagged as possible sycophancy;
6. the report is revised with the top-ranked feedback and ends with **Review notes**: per-model scores, the peer-voted best critique, dissent, critic outcome, flagged citations, and any reviewer that failed.

**See it on a real run:** [docs/examples/jwst-mirror.md](docs/examples/jwst-mirror.md): an OpenAI + Claude panel scored the first draft 4/10; the revised report and its Review notes are reproduced unedited.

![Review notes in the Crossvet web UI after a live run: two vendors, an independent critic and a same-vendor reviser warning](docs/images/web-ui-review-notes.png)

```mermaid
flowchart LR
    Q[Question] --> C[Clarify] --> B[Research brief] --> S[Supervisor]
    S -->|parallel| R1[Researcher] & R2[Researcher] & R3[Researcher]
    R1 & R2 & R3 --> W[(Web search)]
    S --> F[Draft report]
    F --> X{{Cross-vendor review}}
    X -->|critique in parallel| M1[OpenAI] & M2[Anthropic] & M3[Google / local]
    M1 & M2 & M3 --> K[Independent critic<br/>agree / evidence / concern]
    K -.->|optional| D[Deliberation rounds<br/>rotating challenger]
    D -.-> V
    K -->|anonymized ranking| V[Weighted Borda + citation check]
    V --> FR[Revised report + Review notes]
```

## Design principles

Each design choice addresses a documented failure mode of using LLMs to judge LLM output. The papers explain *why* each choice was made; they are not claims that Crossvet reproduces their results.

| Principle | How Crossvet implements it | Evidence |
|---|---|---|
| Reviewers from different vendors | `REVIEW_MODELS` spans vendors; the setup checker warns on a single-vendor panel | Diversity from different models was critical to multi-model consensus gains [1] |
| Confidence-weighted voting | Ballots carry confidence; critiques are ranked with a confidence-weighted Borda count | Confidence-weighted voting across diverse models [1] |
| Anonymize and shuffle before ranking | Critiques become `C1…Cn` in random order before any model ranks them | LLM judges show position and self-enhancement bias [2]; LLMs recognize and favor their own generations [3] |
| Reviser outside the panel | `REVIEW_REVISER_MODEL`, with a warning when it shares a vendor with a reviewer | Self-preference [3]; twelve documented LLM-as-judge biases [4] |
| Hold positions without new evidence | Reviewer and vote prompts reward evidence over confident or agreeable wording | Models trained on human feedback show sycophancy [5] |
| Deterministic citation check | URLs cited in the report are matched against what research actually read | Even strong models often lack complete citation support [6] |
| Evidence-grounded critic | Each finding goes to a critic from a different model than its author; a disagreement counts only with a quote that is verified, in code, to appear in the research notes; unresolved findings go to a *Disputed* section | Structured disagreement between reviewers, with explicit guards against capitulation [7] |
| Position changes need evidence | In deliberation rounds a reviewer may revise or withdraw a finding only with a passage from the notes, verified in code; other changes are ignored and flagged | Models shift answers to agree with a user or a confident challenger [5]; guards against capitulation in reviewer debate [7] |

[1] Chen, Saha & Bansal, *ReConcile: Round-Table Conference Improves Reasoning via Consensus among Diverse LLMs*, ACL 2024. https://aclanthology.org/2024.acl-long.381/
[2] Zheng et al., *Judging LLM-as-a-Judge with MT-Bench and Chatbot Arena*, NeurIPS 2023 (Datasets & Benchmarks). https://arxiv.org/abs/2306.05685
[3] Panickssery, Bowman & Feng, *LLM Evaluators Recognize and Favor Their Own Generations*, NeurIPS 2024. https://arxiv.org/abs/2404.13076
[4] Ye et al., *Justice or Prejudice? Quantifying Biases in LLM-as-a-Judge*, ICLR 2025. https://arxiv.org/abs/2410.02736
[5] Sharma et al., *Towards Understanding Sycophancy in Language Models*, ICLR 2024. https://arxiv.org/abs/2310.13548
[6] Gao, Yen, Yu & Chen, *Enabling Large Language Models to Generate Text with Citations*, EMNLP 2023. https://arxiv.org/abs/2305.14627
[7] Qiu & Gill, *Adversarial Review: Structured Disagreement for Grounded Agentic Code Review*, ICML 2026 DL4C Workshop. https://arxiv.org/abs/2608.18167

## Stack
Python 3.13 · uv · **LangGraph 1.2** (interrupts, SQLite / Postgres checkpointers) · LangChain 1.x (`init_chat_model`, any provider) · **Pydantic v2** typed outputs · **self-hosted models** via Ollama or any OpenAI-compatible server · **Deep Agents** (`deepagents`) edition · **Langfuse** tracing · **MCP** server · pytest · ruff · GitHub Actions · **Agent Chat UI** (Next.js 16, React 19, Tailwind 4) in `web/`.

## Quickstart
Requires Python 3.11–3.13 (the repo pins 3.13 in `.python-version`; `uv` downloads it if needed). Newer Python versions may lack prebuilt packages for some dependencies.

```bash
scripts/quickstart.sh     # checks tools, installs, asks for keys (hidden), picks models your keys can use,
                          # tests each model with one tiny request, runs the setup check and a first research run
```
Or step by step:
```bash
uv sync
uv run crossvet-setup --check                        # writes .env: cross-vendor panel + independent reviser from available models
uv run python -m open_deep_research.doctor           # checks keys, reviewers, search; never prints key values
uv run crossvet-try                                  # one run; saves report, review and a key-free share.md
uv run langgraph dev --config langgraph.local.json   # API on :2024, opens LangGraph Studio

# optional web UI
cd web && cp .env.example .env && pnpm install && pnpm dev   # http://localhost:3000
```

**Search:** `SEARCH_API=tavily` (with `TAVILY_API_KEY`), or `openai` / `anthropic` to use the model's built-in web search with no extra key (`crossvet-setup` picks this when no Tavily key is set). With built-in search, every source the search consulted is added to the research notes, so the citation check still works; Tavily also captures each page's text for the critic to quote.

**Models:** every stage is configurable (`RESEARCH_MODEL`, `SUMMARIZATION_MODEL`, `COMPRESSION_MODEL`, `FINAL_REPORT_MODEL`). Reviewers are set with `REVIEW_MODELS` as `provider:model` strings — `openai:…`, `anthropic:…`, `google_genai:…`, `openrouter:<model>` (with `OPENROUTER_API_KEY`), `ollama:<model>`, or `local:<model>` for any OpenAI-compatible server (llama.cpp, LM Studio, MLX, vLLM) at `LOCAL_LLM_BASE_URL`. At least two reviewers must respond (quorum); failures are reported, not fatal. Set `REVIEW_REVISER_MODEL` to a model from a vendor that is *not* on the panel, so no lab grades and then rewrites its own work; Crossvet adds a warning to the Review notes when the reviser shares a vendor with a reviewer. Turn the stage off with `CROSS_VENDOR_REVIEW_ENABLED=false`.

## Durable runs from the command line
```bash
uv run crossvet run "How are EU AI Act obligations phased in for general-purpose models?" --out report.md
uv run crossvet status --thread <id>      # where did it stop?
uv run crossvet resume --thread <id>      # continue after a crash or Ctrl-C
```
Every step is checkpointed (SQLite by default, Postgres with `DATABASE_URL=postgresql://...` and `uv sync --extra postgres`). A run that crashes mid-way resumes from its last checkpoint without repeating completed — already paid-for — model calls.

**Human approval:** with `REQUIRE_APPROVAL=true` the run pauses after research. Approve, type instructions to steer the report, or reject before any report tokens are spent — at the terminal, or with approve / edit / reject buttons in the web UI. `--auto-approve` skips the prompt.

**Tracing and cost:** set `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY` (and `LANGFUSE_BASE_URL` for a self-hosted Langfuse) and every model call in a CLI run is traced with tokens and cost per model. The LangGraph server also supports LangSmith tracing natively.

## Two editions
- **LangGraph edition** (`deep_researcher`, default): an explicit research graph — brief, supervisor, parallel researchers, compression, report.
- **Deep Agents edition** (`deep_agent`): research and drafting by a LangChain [Deep Agent](https://github.com/langchain-ai/deepagents) that plans with a to-do list, delegates sub-questions to researcher sub-agents and keeps notes in a virtual filesystem.

Both end in the same cross-vendor review. In the Deep Agents edition every search result returned to the agent or a sub-agent is captured by a callback and becomes the research notes, so the citation check, critic and deliberation verify against what was actually retrieved, not against the agent's own summary. With a model's built-in search (`SEARCH_API=openai` or `anthropic`) the sources are read from each model reply instead, including the sub-agents'. Pick the edition in LangGraph Studio or the web UI (`NEXT_PUBLIC_ASSISTANT_ID=deep_agent`), and compare the two with `crossvet-compare --setups examples/compare/editions.toml`.

## Compare models
Run the same questions through different model setups — hosted, OpenRouter, Ollama or a local server, in any role — and compare what each produced:
```bash
uv run crossvet-compare --setups examples/compare/setups.toml --questions examples/compare/questions.txt --repeats 2
```
To compare the models you actually have, let setup write the plan: `uv run crossvet-setup --compare-plan my-setups.toml` creates setups for review vs no review and for each Ollama or local model as report writer and as reviewer (plus deliberation and the Deep Agents edition when available). `examples/compare/questions-15.txt` has 15 questions with checkable answers.

With `LANGFUSE_PUBLIC_KEY` and `LANGFUSE_SECRET_KEY` set, every comparison run is also a Langfuse trace: one session per comparison, tagged `setup:<name>`, with scores attached (finished, cited and flagged URLs, flagged-URL rate, reviewer score, critic drops and disputes, seconds) and token cost per model. `results.jsonl` records each run's trace id.
Each setup is a named set of configuration overrides. Results go to `compare-results/`: one JSON line per run, a per-setup `summary.md` / `summary.csv` (finished runs, latency, input and output tokens, share of cited URLs the research never read, reviewer scores, critic drops and disputes, failed reviewers) and every report for side-by-side reading. A failed run is recorded and the comparison continues.

## Use it from Claude Code, Codex or Cursor (MCP)
`crossvet-mcp` is an MCP server (stdio) with two tools:
- `ask_model(model, prompt)` — ask any configured model, cloud or local;
- `compare_models(prompt, models?)` — ask several models in parallel; per-model failures are reported, never hidden.

```bash
claude mcp add crossvet -- uv --directory /path/to/crossvet run crossvet-mcp
```

## Run export
Set `RUN_EXPORT_PATH=runs/review.jsonl` to append every reviewed run (draft, critiques, critic verdicts, ballots, revision) as one JSON line, for evaluation or fine-tuning.

## Tests
```bash
uv run pytest tests/unit -q     # offline: no API keys, no network
```
Covers anonymization (no vendor leaks into labels), Borda tallying, citation flagging, the critic protocol (fabricated evidence quotes are never trusted), quorum and failure handling, run export, the MCP tools, self-hosted model wiring, the approval step with real LangGraph interrupts, the comparison harness, deliberation and the sycophancy guard, the Deep Agents edition (search capture and report file), and crash-and-resume across two processes (a completed step is never re-run).

## Roadmap
- [x] **v0.1** — cross-vendor review, LangGraph 1.2 / LangChain 1.x upgrade, self-hosted model support, web UI, CI
- [x] **v0.2** — evidence-grounded critic and *Disputed* section, JSONL run export, MCP server (`ask_model`, `compare_models`)
- [x] **v0.3** — durable CLI runs (SQLite / Postgres checkpoints, resume), human approval before the final report, Langfuse tracing
- [x] **v0.4** — model comparison harness: any cloud or local model in any role, compared on citation support, critic outcomes, failures, latency and tokens
- [x] **v0.5** — deeper deliberation: rotating challenger, capped rebuttal rounds, position-change tracking with sycophancy flags
- [x] **v0.6** — Deep Agents edition (planning, sub-agents, virtual filesystem), compared against the LangGraph edition
- [ ] **v0.7** — fine-tuning data path: run exports to MLX LoRA datasets for a self-hosted model, measured before/after
- [ ] **v0.8** — grounded search on self-hosted infrastructure (metasearch, layered page reading, saved evidence, SSRF protection) via MCP
- [ ] **v1.0** — one-command Docker Compose, security scanning in CI, architecture and evaluation docs

## Credits
Built on [Open Deep Research](https://github.com/langchain-ai/open_deep_research) and [Agent Chat UI](https://github.com/langchain-ai/agent-chat-ui) (both MIT). Anonymized model peer review is inspired by Andrej Karpathy's *llm-council*; the critic's agree / disagree-with-evidence / disagree-concern protocol is adapted from the MIT-licensed *review-council* skill and the research it cites. Details in [NOTICES.md](NOTICES.md); the original upstream README is in [docs/UPSTREAM-README.md](docs/UPSTREAM-README.md).

## License
MIT — see [LICENSE](LICENSE) (upstream) and [NOTICES.md](NOTICES.md).
