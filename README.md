# Crossvet

**Deep research whose reports are checked by models from several AI vendors before you see them.**

Crossvet extends LangChain's [Open Deep Research](https://github.com/langchain-ai/open_deep_research) (MIT). A single model writing a research report will state unsupported claims with confidence. Crossvet adds a **cross-vendor review** stage: after the draft report is written,

1. reviewers from different vendors (e.g. OpenAI, Anthropic, Google, or a self-hosted model) critique it **independently and in parallel**, as typed objects;
2. the critiques are **anonymized and shuffled**, and every reviewer ranks them — combined with a **confidence-weighted Borda count**;
3. a **deterministic citation check** flags any URL the report cites that never appeared in the research notes;
4. the report is revised with the top-ranked feedback and ends with **Review notes**: per-model scores, the peer-voted best critique, dissent, flagged citations, and any reviewer that failed.

```mermaid
flowchart LR
    Q[Question] --> C[Clarify] --> B[Research brief] --> S[Supervisor]
    S -->|parallel| R1[Researcher] & R2[Researcher] & R3[Researcher]
    R1 & R2 & R3 --> W[(Web search)]
    S --> F[Draft report]
    F --> X{{Cross-vendor review}}
    X -->|critique in parallel| M1[OpenAI] & M2[Anthropic] & M3[Google / local]
    M1 & M2 & M3 -->|anonymized ranking| V[Weighted Borda + citation check]
    V --> FR[Revised report + Review notes]
```

## Stack
Python 3.13 · uv · **LangGraph 1.2** · LangChain 1.x (`init_chat_model`, any provider) · **Pydantic v2** typed outputs · **self-hosted models** via Ollama or any OpenAI-compatible server · pytest · ruff · GitHub Actions · **Agent Chat UI** (Next.js 16, React 19, Tailwind 4) in `web/`.

## Quickstart
```bash
cp .env.example .env            # add model keys, search key, REVIEW_MODELS
uv sync
uv run langgraph dev --config langgraph.local.json   # API on :2024, opens LangGraph Studio

# optional web UI
cd web && cp .env.example .env && pnpm install && pnpm dev   # http://localhost:3000
```

**Search:** `SEARCH_API=tavily` (with `TAVILY_API_KEY`), or `openai` / `anthropic` to use the model's native web search.

**Models:** every stage is configurable (`RESEARCH_MODEL`, `SUMMARIZATION_MODEL`, `COMPRESSION_MODEL`, `FINAL_REPORT_MODEL`). Reviewers are set with `REVIEW_MODELS` as `provider:model` strings — `openai:…`, `anthropic:…`, `google_genai:…`, `openrouter:<model>` (with `OPENROUTER_API_KEY`), `ollama:<model>`, or `local:<model>` for any OpenAI-compatible server (llama.cpp, LM Studio, MLX, vLLM) at `LOCAL_LLM_BASE_URL`. At least two reviewers must respond (quorum); failures are reported, not fatal. Turn the stage off with `CROSS_VENDOR_REVIEW_ENABLED=false`.

## Tests
```bash
uv run pytest tests/unit -q     # offline: no API keys, no network
```
Covers anonymization (no vendor leaks into labels), Borda tallying, citation flagging, quorum and failure handling, and self-hosted model wiring.

## Roadmap
- [x] **v0.1** — cross-vendor review, LangGraph 1.2 / LangChain 1.x upgrade, self-hosted model support, web UI, CI
- [ ] **v0.2** — grounded search on self-hosted infrastructure (SearXNG metasearch → HTTP / Firecrawl / headless-browser reading, saved evidence, SSRF protection) via MCP
- [ ] **v0.3** — evidence-grounded critic (agree / disagree-with-evidence / disagree-concern) and a *Disputed* section; Postgres checkpointer (crash-and-resume), human approval before the final report, Langfuse tracing with cost per model, MCP server for Claude Code / Codex / Cursor
- [ ] **v0.4** — model comparison harness: any cloud or local model in any role, scored on quality, citation support, cost, latency
- [ ] **v0.5** — Deep Agents edition (planning, sub-agents, virtual filesystem, context management), benchmarked against the LangGraph edition
- [ ] **v0.6** — fine-tuning a self-hosted model (MLX LoRA) on exported runs, measured before/after

## Credits
Built on [Open Deep Research](https://github.com/langchain-ai/open_deep_research) and [Agent Chat UI](https://github.com/langchain-ai/agent-chat-ui) (both MIT). Anonymized model peer review is inspired by Andrej Karpathy's *llm-council*. Details in [NOTICES.md](NOTICES.md); the original upstream README is in [docs/UPSTREAM-README.md](docs/UPSTREAM-README.md).

## License
MIT — see [LICENSE](LICENSE) (upstream) and [NOTICES.md](NOTICES.md).
