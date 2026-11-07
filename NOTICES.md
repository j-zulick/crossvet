# Notices and credits

This project builds on open-source work. Original copyright and license notices are retained.

| Component | Source | License | Pinned at | Used as |
|---|---|---|---|---|
| Open Deep Research | https://github.com/langchain-ai/open_deep_research | MIT (© 2025 LangChain) — see `LICENSE` | `1b7d2e8` | Base research agent (history preserved in this repo) |
| Agent Chat UI | https://github.com/langchain-ai/agent-chat-ui | MIT (© 2025 Brace Sproul) — see `web/LICENSE` | `0d21f7f` | Web frontend in `web/` |
| Deep Agents | https://github.com/langchain-ai/deepagents | MIT | `0.7.34` (dependency) | Agent harness used by the Deep Agents edition; used as a library, no code copied |

## Ideas credited (no code copied)
- **Anonymized peer review between models** — Andrej Karpathy, *llm-council* (https://github.com/karpathy/llm-council). The cross-vendor review here is an independent implementation with typed critiques, confidence-weighted Borda voting, a deterministic citation check and report revision.
- **Multi-model consensus with stances, CLI delegation** — PAL MCP Server (https://github.com/BeehiveInnovations/pal-mcp-server), reviewed as prior art and planned as an evaluation baseline.
- **Critic protocol (agree / disagree-with-evidence / disagree-concern, disputed section)** — review-council skill by Ian Cook (https://github.com/ianpcook/review-council-skill, MIT), which credits Qiu & Gill, *Adversarial Review: Structured Disagreement for Grounded Agentic Code Review* (arXiv:2608.18167). Reimplemented here for research reports; no text copied.
- **Read-only vs write split for agent-to-agent delegation** — Frenemy (https://github.com/noblehacks/frenemy), informs the planned coding-agent workers.

## What is new in this repository
- `src/open_deep_research/cross_vendor_review.py` — cross-vendor review node (critique, anonymized ranking, citation check, revision).
- Self-hosted model support (`ollama:<model>`, `local:<model>`).
- `src/open_deep_research/approval.py`, `cli.py`, `tracing.py`, `mcp_server.py` — approval step, durable CLI, Langfuse tracing, MCP server.
- `src/open_deep_research/compare.py` — model setup comparison harness.
- `src/open_deep_research/deep_agent.py` — Deep Agents edition with captured search results and the shared review.
- `src/open_deep_research/dataset.py` — MLX LoRA dataset builder from run exports.
- `src/open_deep_research/deliberation.py` — deliberation rounds with rotating challengers and grounded position changes.
- `src/open_deep_research/gateway_search.py` — search provider for a self-hosted research gateway over MCP.
- Upgraded to LangGraph 1.2 / LangChain 1.x; Pydantic v2 configuration idioms; Python 3.13.
- `tests/unit/` — offline tests; `.github/workflows/ci.yml`; `langgraph.local.json`.
