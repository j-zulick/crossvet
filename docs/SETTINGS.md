# Settings

Every setting is an environment variable (the upper-case name), usually set in `.env`; copy `.env.example` to start. An empty value means the default. Generated from `src/open_deep_research/configuration.py` by `python -m open_deep_research.settings_doc`; do not edit by hand.

## Run settings

| Setting | Default | What it does |
|---|---|---|
| `MAX_STRUCTURED_OUTPUT_RETRIES` | `3` | Maximum number of retries for structured output calls from models |
| `ALLOW_CLARIFICATION` | `True` | Whether to allow the researcher to ask the user clarifying questions before starting research |
| `MAX_CONCURRENT_RESEARCH_UNITS` | `5` | Maximum number of research units to run concurrently. This will allow the researcher to use multiple sub-agents to conduct research. Note: with more concurrency, you may run into rate limits. |
| `SEARCH_API` | `tavily` | Search API to use for research. NOTE: Make sure your Researcher Model supports the selected search API. |
| `SEARCH_ALSO` | (empty) | Also give researchers a model's built-in web search next to the main search (e.g. your gateway plus OpenAI search). The researcher model must be from the same vendor. |
| `MAX_RESEARCHER_ITERATIONS` | `6` | Maximum number of research iterations for the Research Supervisor. This is the number of times the Research Supervisor will reflect on the research and ask follow-up questions. |
| `MAX_REACT_TOOL_CALLS` | `10` | Maximum number of tool calling iterations to make in a single researcher step. |
| `SUMMARIZATION_MODEL` | `openai:gpt-6-luna` | Model for summarizing research results from Tavily search results |
| `SUMMARIZATION_MODEL_MAX_TOKENS` | `8192` | Maximum output tokens for summarization model |
| `MAX_CONTENT_LENGTH` | `50000` | Maximum character length for webpage content before summarization |
| `RESEARCH_MODEL` | `openai:gpt-6.1-sol` | Model for conducting research. NOTE: Make sure your Researcher Model supports the selected search API. |
| `RESEARCH_MODEL_MAX_TOKENS` | `10000` | Maximum output tokens for research model |
| `SUPERVISOR_MODEL` | (empty) | Orchestration: the model that plans sub-questions, delegates them to researchers and decides when research is done. Must support tool calls. Empty = the research model. |
| `RESEARCHER_MODEL` | (empty) | Research: the model that searches, calls tools and reads sources for each sub-question. Must support tool calls and the selected search API. Empty = the research model. |
| `COMPRESSION_MODEL` | `openai:gpt-6-luna` | Model for compressing research findings from sub-agents. NOTE: Make sure your Compression Model supports the selected search API. |
| `COMPRESSION_MODEL_MAX_TOKENS` | `8192` | Maximum output tokens for compression model |
| `FINAL_REPORT_MODEL` | `openai:gpt-6-luna` | Model for writing the final report from all research findings |
| `FINAL_REPORT_MODEL_MAX_TOKENS` | `10000` | Maximum output tokens for final report model |
| `MCP_CONFIG` | (empty) | MCP server configuration |
| `REQUIRE_APPROVAL` | `False` | Pause after research so a person can approve, steer or reject the final report before it is written. |
| `CROSS_VENDOR_REVIEW_ENABLED` | `False` | Have a council of models from different vendors critique the draft report, vote on the critiques, and revise it. |
| `REVIEW_MODELS` | (empty) | Comma-separated reviewer models, e.g. openai:gpt-5.4-mini,anthropic:claude-sonnet-5-5 or openrouter:<model>; `crossvet-setup` picks them from the models your keys can use. At least two required. |
| `CONTEXT_PACK` | (empty) | Domain pack: which sources count as primary in this field, which claims go stale, and what reviewers should check. Added to the research brief. |
| `RESEARCH_CONTEXT` | (empty) | Who is asking and why (e.g. 'SEO consultant preparing a client audit for a US regional retailer'). Added to the research brief so research and review aim at it. |
| `REVIEW_SUPPORT_CHECKER` | (empty) | Also check that a quoted passage supports the claim made from it: position changes, AGREE / BUILD_ON verdicts, blind-pass points. 'jev' needs TYPESAFE_API_KEY. |
| `REVIEW_SUPPORT_MODEL` | (empty) | Jev model id, e.g. jev-1.14.0 to pin a version (default: TYPESAFE_DEFAULT_MODEL, else jev-latest). |
| `REVIEW_SUPPORT_CLAIM` | `finding` | What the support checker is asked about: the finding itself, or the one-sentence fact the reviewer says the passage states. |
| `REVIEW_SUPPORT_MIN_PROB` | `0.5` | A passage whose support probability is below this does not count as evidence for the claim. |
| `REVIEW_FALLBACK_MODELS` | (empty) | Comma-separated spare reviewer models. When a reviewer fails, the next spare (preferring a vendor not already on the panel) takes its place; the Review notes say who replaced whom. |
| `REVIEW_CALL_TIMEOUT` | `0` | Seconds before a single review call (outline, critique, critic, deliberation, vote, revision) is abandoned and handled as a failure. 0 = no limit. |
| `REVIEW_REVISER_MODEL` | (empty) | Model that revises the report after review. Defaults to the final report model. Pick one from a vendor that is not on the review panel so no lab grades and rewrites its own work. |
| `REVIEW_CRITIC_ENABLED` | `True` | Before voting, have an independent critic check each reviewer finding against the research notes (agree / disagree with evidence / disagree concern). Unresolved findings are reported as disputed. |
| `REVIEW_BLIND_PASS_ENABLED` | `False` | Before reading the draft, each reviewer outlines the answer from the research notes alone. Grounded points the draft omits are added to the feedback (one short extra call per reviewer). |
| `REVIEW_BLIND_MAX_POINTS` | `6` | Points per blind outline. |
| `REVIEW_BLIND_MAX_TOKENS` | `1500` | Maximum output tokens for a blind outline (keeps the extra call cheap; reasoning models count their thinking against it). |
| `REVIEW_DELIBERATION_ROUNDS` | `0` | Deliberation rounds before voting (0 = off). Each round a rotating challenger contests findings and the author answers; a change of position counts only with a passage from the research notes, and ungrounded changes are flagged as possible sycophancy. |
| `REVIEW_DELIBERATION_EARLY_STOP` | `True` | Stop deliberation before the round cap when code finds consensus (no finding moved and challengers endorse enough findings) or a stable disagreement (nothing moved for two rounds). Off: stop only when nobody contests anything. |
| `REVIEW_CONSENSUS_THRESHOLD` | `1.0` | Share of findings the challengers must endorse (AGREE) in a round with no changes for deliberation to stop early. 1.0 = unanimous. |
| `REVIEW_DELIBERATION_MIN_ROUNDS` | `1` | Deliberation never stops early before this round. |
| `REVIEW_CONSENSUS_MIN_GROUNDED_SHARE` | `0.5` | False-consensus guard: if fewer endorsements than this share cite a passage found in the notes (or the challengers were silent), one more round runs with the next challenger before stopping. 0 = guard off. |
| `RUN_EXPORT_PATH` | (empty) | Optional JSONL file to append each reviewed run to (draft, critiques, critic verdicts, ballots, revision) for evaluation or fine-tuning. |
| `REVIEW_MODEL_MAX_TOKENS` | `8000` | Maximum output tokens per reviewer call (reasoning models count their thinking against this limit) |
| `MCP_PROMPT` | (empty) | Any additional instructions to pass along to the Agent regarding the MCP tools that are available to it. |

## Read from the environment directly

| Variables | What they do |
|---|---|
| `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `GOOGLE_API_KEY` | Model provider keys; set the ones you use. |
| `OPENROUTER_API_KEY` | One key for many models: `openrouter:<maker>/<model>` anywhere a model is set. |
| `OPENROUTER_PROVIDER_ORDER`, `OPENROUTER_ALLOW_FALLBACKS`, `OPENROUTER_DATA_COLLECTION` | Which OpenRouter hosts serve a model, whether others may, and whether prompts may be stored. |
| `OPENROUTER_APP_TITLE`, `OPENROUTER_APP_URL` | App name and URL sent to OpenRouter (default Crossvet and the repository URL). |
| `LOCAL_LLM_BASE_URL`, `LOCAL_LLM_API_KEY` | Any OpenAI-compatible server, for `local:<model>`. |
| `TAVILY_API_KEY` | Tavily search, when `SEARCH_API=tavily`. |
| `RESEARCH_GATEWAY_URL`, `RESEARCH_GATEWAY_TOKEN`, `RESEARCH_GATEWAY_TOOL` | The self-hosted research gateway, when `SEARCH_API=gateway`. |
| `TYPESAFE_API_KEY`, `TYPESAFE_DEFAULT_MODEL` | Jev support checks (billed by TypeSafe); the model defaults to jev-latest. |
| `CROSSVET_CHECKPOINTS`, `DATABASE_URL` | Where CLI runs keep checkpoints: SQLite path (default `.crossvet/checkpoints.sqlite`) or Postgres. |
| `CROSSVET_CACHE_DIR` | Cache for the OpenRouter model catalog (default `~/.cache/crossvet`). |
| `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY`, `LANGFUSE_BASE_URL` | Langfuse tracing with cost per model. |
| `LANGSMITH_API_KEY`, `LANGSMITH_PROJECT`, `LANGSMITH_TRACING` | LangSmith tracing (upstream). |
| `GET_API_KEYS_FROM_CONFIG`, `SUPABASE_URL`, `SUPABASE_KEY` | Hosted deployments only (upstream): keys from the run config, and auth. |
