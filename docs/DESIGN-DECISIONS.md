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

## 12. Stop deliberation in code, not by a model's say-so
**Context.** Fixed rounds spend two model calls per critique per round even after reviewers have converged. Debate that adapts how long it runs performs better than fixed debate (Liang et al., EMNLP 2024). Similar ideas appear in [*consilium*](https://github.com/terry-li-hm/consilium-py) (Terry Li, MIT): debaters say AGREE, DISAGREE or BUILD ON, and a debate ends early when most non-challengers agree.
**Decision.** Reimplemented, not copied. Challengers label every finding AGREE, DISAGREE or BUILD_ON with an optional quote. The stop is a pure function of those typed verdicts and of what changed (`deliberation.decide_stop`): consensus needs a round in which nothing moved and enough endorsements; a stable disagreement ends after two rounds without movement. A BUILD_ON is applied only with a quote found in the notes. Agreement is not trusted on its own: if too few endorsements cite the notes, or the challenger was silent, a guard runs one more round with the next challenger. The challenger is never the author, so the author's own view never counts toward consensus.
**Cost.** The guard can make a run longer than v1.0's (a silent challenger used to end deliberation at once). Unanimity is the default, so early stops happen less often than with a majority rule; `REVIEW_CONSENSUS_THRESHOLD` trades cost against caution. The saving is measured, not assumed: compare `deliberation-3-fixed` and `deliberation-3-early-stop`.

## 13. A blind pass aimed at omissions
**Context.** Reviewers who read a draft first tend to check its claims and miss what it leaves out. [*consilium*](https://github.com/terry-li-hm/consilium-py) (MIT) has debaters commit to short claims before seeing each other, to stop the first speaker anchoring the rest.
**Decision.** Crossvet points the same idea at the draft, not at other reviewers: each reviewer outlines the answer from the notes before reading the draft, with a supporting passage per point. Code grounds every point in the notes and checks coverage in the draft; only grounded omissions become feedback. The outline is shown to its author during the critique so the point is not forgotten. Opt-in.
**Cost.** One short extra call per reviewer. Coverage is lexical: a correct paraphrase can be flagged as an omission. The flag goes to the reviser as feedback, not into the report, and the run export keeps every outline for audit.

## 14. The user picks the panel; Crossvet checks it
**Context.** Model names change monthly, and people want their own mix: a favourite model, a cheap one, a self-hosted one, or vendors such as Grok, GLM or Kimi reached through OpenRouter.
**Decision.** No fixed vendor list. Setup suggests a panel from what the keys can call, but a panel the user set (`--panel`, or an existing `REVIEW_MODELS`) is kept and only checked: unknown names, a single-vendor panel and a reviser that shares a vendor are reported, not silently fixed. Diversity is judged by the model's maker, so OpenRouter host routing (who serves an open-weight model) is a separate, optional setting. Spare reviewers keep a panel diverse when one vendor is down.
**Cost.** A kept panel can go stale; setup reports names the key can no longer call, and `--auto` re-picks.

## 15. A decision model checks support; code still checks the quote
**Context.** Since v0.5 a position change needs a quote that appears verbatim in the notes. That blocks invented evidence, not real evidence used for the wrong claim, and an LLM asked "does this support that?" answers in prose and is poorly calibrated.
**Decision.** Keep the verbatim check as the first gate and add an optional second one: a yes/no question per (claim, passage) to Jev, TypeSafe's System One decision model, which returns a probability. It gates position changes, AGREE / BUILD_ON verdicts and blind-pass points against `REVIEW_SUPPORT_MIN_PROB`. A failed Jev call never blocks: that claim falls back to the quote check and the failure is reported. Scores and the model id that answered are kept in the export, so a threshold can be tuned against a pinned version.
**Cost.** One small request per scored pair (bounded concurrency, about 2 KB of state each). A false "not supported" keeps a finding the panel wanted to drop; that errs toward caution, and the export shows every score for review. Jev is another vendor dependency, so it is off unless `REVIEW_SUPPORT_CHECKER=jev`.

## 17. Score each role with an answer key, not a judge model
**Context.** "Which model is best?" has no single answer for a pipeline: orchestration, search, compression, writing, review and revision reward different strengths, and price differences between models are large. Asking a model to grade other models would bring back the biases the cross-vendor review is designed to remove (self-preference, position effects, confident wording).
**Decision.** `crossvet-bench` tests one role at a time on frozen synthetic inputs, with the production prompt, schema, output limit and turn cap, and scores it with code: planted errors with known answers, facts and URLs that must survive, aspect checklists, citation checks. The critic is scored by balanced accuracy so blanket agreement earns 0.5. Results become configuration through best-quality and best-value role maps; `live-plan` hands one role to `crossvet-compare` to confirm on real questions.
**Cost.** String checks are strict and can miss a correct answer phrased differently, so every job keeps the model's output for audit. Six cases is small; the leaderboard shows standard errors and supports `--repeats`. Synthetic cases measure decisions, not the reach of a live search engine; full runs remain the end-to-end check.

