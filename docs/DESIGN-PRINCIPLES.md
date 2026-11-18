# Design principles

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
| Outline before reading the draft | With the blind pass, reviewers list the points a correct answer needs, each with a passage from the notes, before they see the draft; code adds grounded points the draft omits to the feedback | LLM judges anchor on what they are shown, including position and order [2] |
| A real quote can still be the wrong evidence | With `REVIEW_SUPPORT_CHECKER=jev`, every passage used to change a position, endorse, extend a finding or ground a blind-pass point is scored by a decision model for whether it supports that claim; low scores don't count | Verbatim matching catches invented quotes, not misused ones; LLM judges are poorly calibrated about their own agreement [5] |
| Stop debating when it stops helping | Code ends deliberation on consensus or a stable disagreement; endorsements that cite nothing in the notes buy one more round instead of ending it | An adaptive break of debate was needed for multi-agent debate to perform well [8]; agreement is not evidence [5] |

[1] Chen, Saha & Bansal, *ReConcile: Round-Table Conference Improves Reasoning via Consensus among Diverse LLMs*, ACL 2024. https://aclanthology.org/2024.acl-long.381/
[2] Zheng et al., *Judging LLM-as-a-Judge with MT-Bench and Chatbot Arena*, NeurIPS 2023 (Datasets & Benchmarks). https://arxiv.org/abs/2306.05685
[3] Panickssery, Bowman & Feng, *LLM Evaluators Recognize and Favor Their Own Generations*, NeurIPS 2024. https://arxiv.org/abs/2404.13076
[4] Ye et al., *Justice or Prejudice? Quantifying Biases in LLM-as-a-Judge*, ICLR 2025. https://arxiv.org/abs/2410.02736
[5] Sharma et al., *Towards Understanding Sycophancy in Language Models*, ICLR 2024. https://arxiv.org/abs/2310.13548
[6] Gao, Yen, Yu & Chen, *Enabling Large Language Models to Generate Text with Citations*, EMNLP 2023. https://arxiv.org/abs/2305.14627
[7] Qiu & Gill, *Adversarial Review: Structured Disagreement for Grounded Agentic Code Review*, ICML 2026 DL4C Workshop. https://arxiv.org/abs/2608.18167
[8] Liang et al., *Encouraging Divergent Thinking in Large Language Models through Multi-Agent Debate*, EMNLP 2024. https://aclanthology.org/2024.emnlp-main.992/
