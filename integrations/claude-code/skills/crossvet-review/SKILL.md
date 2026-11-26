---
name: crossvet-review
description: Use when the user asks for a second opinion, an outside review, or a review "by another model" of a code change, or before committing a risky change. Runs Crossvet so a model from another vendor reviews the diff, and only findings that match the diff are reported.
---

# Second-vendor review with Crossvet

Crossvet (`crossvet` on the PATH; install with `uv tool install "git+https://github.com/j-zulick/crossvet"`) sends the diff to a reviewer from a different vendor than the model that wrote it, and keeps only findings whose file, line and quote match the diff.

## Steps
1. Decide what to review: the staged change (`--staged`), this branch (`--base main`), or a diff on standard input.
2. Run `crossvet review --staged --task "<what the change is meant to do>" --json` and read the JSON: `kept` are findings that passed the checks, `dropped` were removed with a reason.
3. Report each kept finding with `file:line`, severity, the problem and the suggested fix. Read the code at each line yourself and say whether you agree.
4. Only when the user asks for fixes: `crossvet review --staged --task "..." --fix` (a patch checked with `git apply --check`), and `--apply --rounds 2` to apply it and review again.

## Notes
- `--author` names the model that wrote the change (default: the user's default model); the reviewer comes from the reviewer slot, from another vendor.
- Every review leaves a decision record in `.crossvet/reviews/`.
- If Crossvet says no model from another vendor is in reach, the user needs a second provider's key; say so instead of reviewing with the same vendor.
