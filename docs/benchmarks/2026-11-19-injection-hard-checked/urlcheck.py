"""Re-run v1.9's unverified-URL check on the writer reports of this run.

    uv run python docs/benchmarks/2026-11-19-injection-hard-checked/urlcheck.py

The benchmark's writer role does not run the review, so this applies
``injection_check.urls_only_in_text`` to each report, with the case's sources formatted the way
the research tools write them (one block per page with a ``URL:`` line).
"""
import json
from pathlib import Path

from open_deep_research.bench_cases import SUITES
from open_deep_research.injection_check import urls_only_in_text

cases = {c["id"]: c for c in SUITES["injection-hard-checked"]}


def pipeline_notes(case: dict) -> str:
    return "\n\n".join(f"--- SOURCE {i}: {s['title']} ---\nURL: {s['url']}\n\n{s['text']}"
                       for i, s in enumerate(case["sources"], 1))


rows = [json.loads(line) for line in (Path(__file__).parent / "results.jsonl").read_text().splitlines()]
writers = [r for r in rows if r["role"] == "writer" and r["quality"] is not None]
for r in writers:
    hits = urls_only_in_text(r["details"]["output"], pipeline_notes(cases[r["case"]]))
    if hits:
        print(r["model"], r["case"], hits)
print(f"{len(writers)} writer reports checked")
