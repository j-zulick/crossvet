---
description: Have a model from another vendor review the staged change (or this branch) with Crossvet
argument-hint: "[what the change is meant to do]"
allowed-tools: Bash(crossvet review:*), Bash(git diff:*), Bash(git status:*)
---

Review the current change with a second vendor through Crossvet.

1. Run `git status --short`. If something is staged, review the staged change; otherwise review this branch against `main` with `--base main`.
2. Run `crossvet review --staged --task "$ARGUMENTS"` (or `crossvet review --base main --task "$ARGUMENTS"`). If no task was given, write a one-line task from the diff.
3. Show the findings it kept, grouped by severity, each with its `file:line`. Say how many it dropped by its checks, and give the path of the decision record.
4. For each kept finding, say whether you agree after reading the code at that line. Do not edit files unless I ask; if I do, `crossvet review --staged --task "..." --fix` writes a patch that `git apply --check` accepts.
