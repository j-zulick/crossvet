"""Turn exported runs into fine-tuning data for a self-hosted model (MLX LoRA).

Every reviewed run can be appended to a JSONL file (``RUN_EXPORT_PATH``). This module
converts those records into chat-format datasets that ``mlx_lm.lora`` reads directly,
for two jobs a small local model can learn from stronger hosted ones:

- ``critique``: research notes + draft report → the critique the panel voted most
  useful, after the critic (and any deliberation) removed findings the notes contradict.
- ``revise``: research notes + draft + review feedback → the revised report, kept only
  when the revision succeeded and cites nothing the research did not read.

    crossvet-dataset --runs runs/review.jsonl --task critique --out data/critique

Writes ``train.jsonl``, ``valid.jsonl`` and ``test.jsonl`` (about 80/10/10). The split is
by research brief, so the same question never appears in two splits. Then, on a Mac::

    mlx_lm.lora --model <model> --train --data data/critique --iters 600 --mask-prompt
    mlx_lm.lora --model <model> --adapter-path adapters --data data/critique --test
    mlx_lm.fuse --model <model>                  # writes fused_model/
    mlx_lm.server --model fused_model            # OpenAI-style API on localhost:8080

and compare the base and fused model as a ``local:`` reviewer with ``crossvet-compare``.

Exports contain text fetched from the web. Check the terms of your sources before
training on them, and keep the datasets private.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Iterable

from open_deep_research.cross_vendor_review import (
    CRITIQUE_PROMPT,
    REVISE_PROMPT,
    Critique,
    check_citations,
)

TASKS = ("critique", "revise")
SYSTEM = {
    "critique": "You are a rigorous reviewer of research reports. Return your critique as JSON.",
    "revise": "You revise research reports so every claim is supported by the research notes.",
}


def read_runs(path: str | Path) -> Iterable[dict[str, Any]]:
    """Yield run records, skipping blank or malformed lines."""
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(record, dict):
                yield record


def _date(record: dict[str, Any]) -> str:
    return str(record.get("exported_at", ""))[:10] or "unknown"


def critique_example(record: dict[str, Any]) -> tuple[dict[str, Any] | None, str]:
    """Build a critique example, or return (None, reason it was skipped)."""
    notes, draft = record.get("research_notes"), record.get("draft_report")
    if not notes or not draft:
        return None, "no research notes in export (needs schema_version 2)"
    tally, labels, critiques = record.get("tally") or [], record.get("labels") or {}, record.get("critiques") or {}
    if len(record.get("ballots") or []) < 2 or not tally:
        return None, "fewer than two ballots"
    best_model = labels.get(tally[0][0])
    data = critiques.get(best_model or "")
    if not data:
        return None, "top-voted critique missing"
    critique = Critique.model_validate(data)
    if not (critique.unsupported_claims or critique.factual_concerns or critique.missing_perspectives or critique.suggested_revisions):
        return None, "top-voted critique is empty"
    prompt = CRITIQUE_PROMPT.format(date=_date(record), brief=record.get("research_brief", ""), notes=notes, report=draft)
    return {"messages": [
        {"role": "system", "content": SYSTEM["critique"]},
        {"role": "user", "content": prompt},
        {"role": "assistant", "content": critique.model_dump_json()},
    ]}, ""


def revise_example(record: dict[str, Any]) -> tuple[dict[str, Any] | None, str]:
    """Build a revision example, or return (None, reason it was skipped)."""
    notes, draft, revised = record.get("research_notes"), record.get("draft_report"), record.get("revised_report")
    feedback = record.get("revision_feedback")
    if not notes or not draft or feedback is None:
        return None, "no research notes or feedback in export (needs schema_version 2)"
    if not revised or not record.get("revision_ok", revised != draft):
        return None, "revision failed"
    if check_citations(revised, notes):
        return None, "revised report cites URLs the research never read"
    prompt = REVISE_PROMPT.format(date=_date(record), notes=notes, report=draft, feedback=feedback)
    return {"messages": [
        {"role": "system", "content": SYSTEM["revise"]},
        {"role": "user", "content": prompt},
        {"role": "assistant", "content": revised},
    ]}, ""


BUILDERS = {"critique": critique_example, "revise": revise_example}


def split_for(brief: str) -> str:
    """Deterministic split by research brief: about 80% train, 10% valid, 10% test."""
    bucket = int(hashlib.sha256(brief.strip().lower().encode()).hexdigest(), 16) % 10
    return "test" if bucket == 0 else "valid" if bucket == 1 else "train"


def build(runs: Iterable[dict[str, Any]], task: str, max_chars: int = 0) -> tuple[dict[str, list[dict[str, Any]]], Counter]:
    """Build split datasets for a task; returns (splits, skip reasons)."""
    builder = BUILDERS[task]
    splits: dict[str, list[dict[str, Any]]] = {"train": [], "valid": [], "test": []}
    skipped: Counter = Counter()
    seen: set[str] = set()
    for record in runs:
        example, reason = builder(record)
        if example is None:
            skipped[reason] += 1
            continue
        if max_chars and sum(len(m["content"]) for m in example["messages"]) > max_chars:
            skipped["longer than --max-chars"] += 1
            continue
        key = hashlib.sha256(json.dumps(example, sort_keys=True).encode()).hexdigest()
        if key in seen:
            skipped["duplicate"] += 1
            continue
        seen.add(key)
        splits[split_for(record.get("research_brief", ""))].append(example)
    return splits, skipped


def write(splits: dict[str, list[dict[str, Any]]], out: Path) -> None:
    """Write train/valid/test JSONL files, one example per line."""
    out.mkdir(parents=True, exist_ok=True)
    for name, rows in splits.items():
        with open(out / f"{name}.jsonl", "w", encoding="utf-8") as fh:
            for row in rows:
                fh.write(json.dumps(row, ensure_ascii=False) + "\n")


def main(argv: list[str] | None = None) -> int:
    """Command-line entry point."""
    p = argparse.ArgumentParser(prog="crossvet-dataset", description="Build MLX LoRA datasets from exported Crossvet runs.")
    p.add_argument("--runs", required=True, help="JSONL file written via RUN_EXPORT_PATH")
    p.add_argument("--task", choices=TASKS, required=True)
    p.add_argument("--out", required=True, help="output directory for train/valid/test.jsonl")
    p.add_argument("--max-chars", type=int, default=0, help="skip examples longer than this many characters (0 = no limit)")
    args = p.parse_args(argv)
    try:
        splits, skipped = build(read_runs(args.runs), args.task, args.max_chars)
    except OSError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    write(splits, Path(args.out))
    total = sum(len(v) for v in splits.values())
    print(f"{args.task}: {total} examples (train {len(splits['train'])}, valid {len(splits['valid'])}, test {len(splits['test'])}) in {args.out}")
    for reason, n in skipped.most_common():
        print(f"  skipped {n}: {reason}")
    if not splits["train"] or not splits["test"]:
        print("warning: mlx_lm.lora needs train.jsonl for --train and test.jsonl for --test; export more runs.", file=sys.stderr)
    return 0 if total else 1


if __name__ == "__main__":
    raise SystemExit(main())
