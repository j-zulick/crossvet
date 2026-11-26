---
name: crossvet-review
description: Get a second-vendor review of the current change through Crossvet; only findings that match the diff are reported.
---

# Second-vendor review with Crossvet (Codex)

Copy this folder to `~/.codex/skills/crossvet-review/`. It needs the `crossvet` command and keys for two vendors.

1. Stage the change, or note the base branch.
2. Run `crossvet review --staged --task "<what the change does>" --json` (or `--base main`).
3. Report the `kept` findings with `file:line`, severity, problem and fix; mention how many were `dropped` by the checks.
4. Apply nothing unless asked. When asked: `crossvet review --staged --task "..." --fix --apply --rounds 2`.

Crossvet picks a reviewer from another vendor than the author model (`--author`, default: the user's default model). The decision record is written to `.crossvet/reviews/`.
