# Design decisions

Short records of the choices that shape Crossvet: the context, the decision, and what it costs. Research behind several of them is cited in the README's *Design principles*.

## 1. Extend Open Deep Research instead of starting over
**Context.** A credible deep-research agent needs search, parallel researchers, compression and report writing before any review can be added.
**Decision.** Build on LangChain's Open Deep Research (MIT), keep its history, and add Crossvet as new modules and nodes.
**Cost.** Inherited behaviour (for example, environment variables overriding run configuration) is kept and documented rather than redesigned.

## 2. Review by models from different vendors
**Context.** Models from one family share training data and blind spots, and judges favour their own outputs.
**Decision.** `REVIEW_MODELS` lists reviewers from different vendors; the setup checker warns on a single-vendor panel; `vendor_of()` maps OpenRouter and self-hosted routes to the real maker.
**Cost.** Several API keys (or one OpenRouter key) and more calls per report.

## 3. Deterministic checks wherever a check can be deterministic
**Context.** An LLM judge can be persuaded; a string comparison cannot.
**Decision.** Cited URLs are compared with the research notes in code. Evidence quotes from the critic and from deliberation count only if they appear verbatim (ignoring case and whitespace) in the notes.
**Cost.** URL matching does not prove a page supports a claim; that judgement stays with the critic and is reported as such.

## 4. Anonymize before ranking; revise outside the panel
**Context.** Position and self-preference biases are documented for LLM judges.
**Decision.** Critiques are shuffled and relabelled before voting; the reviser is configurable and flagged when it shares a vendor with a reviewer.
**Cost.** Label shuffling makes runs less reproducible; the mapping is recorded in the export.

## 5. Position changes need evidence
**Context.** Models tend to agree with confident pushback (sycophancy), which can make debate converge on the wrong answer.
**Decision.** Deliberation is off by default, capped at three rounds, and applies a revision or withdrawal only with a quote verified in the notes. Ungrounded changes are ignored and counted.
**Cost.** A correct change argued without a quote is ignored; the count makes that visible.

## 6. Failures degrade, they don't end runs
**Context.** Multi-vendor review multiplies the chance that some provider fails.
**Decision.** Every reviewer, critic, challenger and voter call is isolated. A quorum of two is required for review; failures are listed in the Review notes; comparison runs record errors and continue.
**Cost.** A report can be published with partial review; the notes say exactly which part.

## 7. Two editions, one review
**Context.** LangChain's Deep Agents is a newer, more autonomous way to build the same kind of agent.
**Decision.** Ship it as a second graph with the identical review, and capture its search results with a callback so grounding does not depend on the agent following instructions. Compare the two with `crossvet-compare` instead of asserting which is better.
**Cost.** One more dependency and two research paths to maintain.

## 8. Measure before claiming
**Context.** Claims about quality need evidence.
**Decision.** `crossvet-compare` produces per-setup tables from real runs; [EVALS.md](EVALS.md) records the protocol and results, including losses.
**Cost.** Results take paid runs and human grading.

## 9. Self-hosted first-class
**Context.** Local models are useful for privacy, cost and fine-tuning.
**Decision.** `ollama:` and `local:` models work in any role; run exports convert into MLX LoRA datasets; a fine-tuned model is evaluated as a `local:` reviewer.
**Cost.** Local models often handle structured output less reliably; failures surface as failed reviewers.

## 10. Keep `config_schema` for now
**Context.** LangGraph 1.x deprecates `config_schema` in favour of `context_schema`, with removal planned for 2.0.
**Decision.** Keep `config_schema`: LangGraph Studio's configuration panel and every node read settings from `configurable`, and migrating changes how users pass settings. Migrate together with the LangGraph 2.0 upgrade.
**Cost.** A deprecation warning at import time.

## 11. Secrets never leave `.env`
**Decision.** Keys come only from the environment. The setup checker reports presence, never values; Docker images contain no keys; CI scans history for secrets on every push.
