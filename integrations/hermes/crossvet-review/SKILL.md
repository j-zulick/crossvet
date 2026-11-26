---
name: crossvet-review
description: Before a commit or pull request, have a model from another vendor review the change through Crossvet, and report only findings that match the diff.
---

# Second-vendor review with Crossvet (Hermes)

Copy this folder to `~/.hermes/skills/crossvet-review/`. Hermes runs the `crossvet` command in the repository it is working in.

1. In the repository, stage the change Hermes made.
2. Run `crossvet review --staged --task "<the task Hermes was given>" --author <the model Hermes used> --json`.
3. If `kept` is empty, continue. Otherwise read each finding's `file:line`, fix what holds up, stage again and repeat once.
4. Put the decision record path from `.crossvet/reviews/` in the commit or pull request description.

With Crossvet as Hermes's model provider (`crossvet start`), `--author` is the model Hermes's `/model` picked; the reviewer comes from another vendor.
