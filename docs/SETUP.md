# Setup

The [README](../README.md#quick-start) covers installing a release and `crossvet setup`. This page covers working from a clone, Docker, search sources, choosing models for every role, and the MCP servers. Every setting: [SETTINGS.md](SETTINGS.md).

## From a clone
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
uv run crossvet-doctor --jev                         # same checker as a command; --jev asks Jev two known questions
uv run crossvet-try                                  # one run; saves report, review and a key-free share.md
uv run langgraph dev --config langgraph.local.json   # API on :2024, opens LangGraph Studio

# optional web UI
cd web && cp .env.example .env && pnpm install && pnpm dev   # http://localhost:3000
```

**Or with Docker** — one command for the API (both editions) and the web UI, bound to localhost:
```bash
cp .env.example .env            # add your keys; every setting: docs/SETTINGS.md
docker compose up --build       # API http://localhost:2024 · web UI http://localhost:3000
```

**Search:** `SEARCH_API=gateway` (with `RESEARCH_GATEWAY_URL` and `RESEARCH_GATEWAY_TOKEN`), `tavily` (with `TAVILY_API_KEY`), or `openai` / `anthropic` to use the model's built-in web search with no extra key (`crossvet-setup` picks this when no Tavily key is set). With built-in search, every source the search consulted is added to the research notes, so the citation check still works; the gateway and Tavily also capture each page's text for the critic to quote. **Combined search:** add `SEARCH_ALSO=openai` (or `anthropic`) to give researchers the model's built-in search next to the gateway or Tavily, so research continues if one source returns nothing; the researcher model must be from that vendor.

**Models:** every stage is configurable (`RESEARCH_MODEL`, `SUPERVISOR_MODEL` for orchestration, `RESEARCHER_MODEL`, `SUMMARIZATION_MODEL`, `COMPRESSION_MODEL`, `FINAL_REPORT_MODEL`), and so is every review role. Any setting takes a `provider:model` string: `openai:…`, `anthropic:…`, `google_genai:…`, `openrouter:<maker>/<model>` (with `OPENROUTER_API_KEY`), `ollama:<model>`, or `local:<model>` for any OpenAI-compatible server (llama.cpp, LM Studio, MLX, vLLM) at `LOCAL_LLM_BASE_URL`. Reviewers are set with `REVIEW_MODELS`. At least two reviewers must respond (quorum); failures are reported, not fatal. Set `REVIEW_REVISER_MODEL` to a model from a vendor that is *not* on the panel, so no lab grades and then rewrites its own work; Crossvet adds a warning to the Review notes when the reviser shares a vendor with a reviewer. Turn the stage off with `CROSS_VENDOR_REVIEW_ENABLED=false`.

## Choose your own models
Crossvet doesn't fix a vendor list: any model your keys can call can sit on the panel, revise, or run a stage. `crossvet-setup` only suggests.
```bash
uv run crossvet-setup --list-models openrouter --filter grok        # every id a provider offers (openai, anthropic, google_genai, openrouter, ollama, local)
uv run crossvet-setup --panel openrouter:x-ai/grok-4.7,anthropic:claude-opus-5-5,openrouter:z-ai/glm-5.3 --reviser google_genai:gemini-3.1-pro-preview
```
- **Your choice sticks.** Once `REVIEW_MODELS` is set, re-running setup keeps it and only checks it: names your key cannot call, a single-vendor panel, or a reviser that shares a vendor with the panel are reported. `--auto` re-picks; `--panel` replaces.
- **Wide vendor coverage through OpenRouter.** One `OPENROUTER_API_KEY` adds vendors such as xAI (Grok), Z.ai (GLM), Moonshot (Kimi), DeepSeek, Qwen, Mistral and Meta; the automatic pick takes the newest model per vendor not already on the panel. The vendor that counts for diversity is the model's maker (`openrouter:z-ai/glm-5` → `z-ai`).
- **Who hosts an OpenRouter model** (not which model runs): `OPENROUTER_PROVIDER_ORDER` (hosts to try first), `OPENROUTER_ALLOW_FALLBACKS=false` (only those hosts) and `OPENROUTER_DATA_COLLECTION=deny` (only hosts that don't store or train on prompts).
- **Spares and time limits.** `REVIEW_FALLBACK_MODELS` lists spare reviewers; when one fails, the next spare takes its place, preferring a vendor not already on the panel, and the Review notes say who replaced whom. `REVIEW_CALL_TIMEOUT` (seconds, 0 = off) abandons any single review call that hangs and handles it as a failure.

## Use it from Claude Code, Codex or Cursor (MCP)
`crossvet-mcp` is an MCP server (stdio) with three tools:
- `ask_model(model, prompt)` — ask any configured model, cloud or local;
- `compare_models(prompt, models?)` — ask several models in parallel; per-model failures are reported, never hidden;
- `scan_for_injection(url | text)` — check a public page or pasted HTML for prompt injection, by channel; non-public addresses are refused.

```bash
claude mcp add crossvet -- uv --directory /path/to/crossvet run crossvet-mcp
```
