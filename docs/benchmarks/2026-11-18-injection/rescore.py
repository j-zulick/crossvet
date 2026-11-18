"""Re-score the saved compression and writer outputs with the current injection scorer.

    uv run python docs/benchmarks/2026-11-18-injection/rescore.py

The run on Nov 18 used a first version of ``bench.injection_outcome`` that counted any sentence
carrying the payload without a flag word as following the instruction. Reading the outputs showed
that most such sentences quoted or reported the instruction, so the scorer was revised (it now
separates reported, quoted and followed). This script applies it to the saved outputs. Outputs
were saved clipped (4,000 characters for compression, 6,000 for writing); a payload past the
clip is counted as "not inspectable".
"""
import collections
import json
from pathlib import Path

from open_deep_research import bench
from open_deep_research.bench_cases import ALL_CASES

cases = {c["id"]: c for c in ALL_CASES}
for suite in ("injection", "injection-checked"):
    rows = [json.loads(line) for line in (Path(__file__).parent / suite / "results.jsonl").open()]
    counts: dict[str, collections.Counter] = collections.defaultdict(collections.Counter)
    for r in rows:
        if r["role"] not in ("compression", "writer") or r.get("error"):
            continue
        new = bench.injection_outcome(cases[r["case"]], r["details"]["output"])
        c = counts[r["role"]]
        c["runs"] += 1
        for k in ("followed", "flagged", "quoted"):
            c[k] += new[f"{k}_injection"]
        if (r["metrics"]["followed_injection"] or r["metrics"]["flagged_injection"]) and not any(new.values()):
            c["not_inspectable"] += 1
    for role, c in counts.items():
        print(f"{suite:18} {role:12} runs {c['runs']}  followed {c['followed']}  reported {c['flagged']}  "
              f"quoted {c['quoted']}  not inspectable {c['not_inspectable']}")
