"""Count compression outcomes with the current injection scorer, per form, for this run and the defenses run.

    uv run python docs/benchmarks/2026-11-19-injection-hard-checked/compression_counts.py \\
      docs/benchmarks/2026-11-18-injection-defenses/results.jsonl docs/benchmarks/2026-11-19-injection-hard-checked/results.jsonl
"""
import json, sys
from open_deep_research import bench
from open_deep_research.bench_cases import ALL_CASES
cases={c["id"]:c for c in ALL_CASES}
def counts(path, field):
    rows=[json.loads(l) for l in open(path)]
    by={}
    for r in rows:
        if r["role"]!="compression" or r.get("error") or r["quality"] is None: continue
        m=bench.injection_outcome(cases[r["case"]], r["details"][field]) if field=="output" else None
        f=cases[r["case"]]["injection"]["form"]; d=by.setdefault(f,[0,0,0,0,0])
        d[0]+=1; d[1]+=m["followed_injection"]>0; d[2]+=(m["followed_injection"] or m["quoted_injection"])>0; d[3]+=m["flagged_injection"]>0; d[4]+=m["quoted_injection"]>0
    tot=[sum(v[i] for v in by.values()) for i in range(5)]
    return by, tot
for p in sys.argv[1:]:
    by,tot=counts(p,"output"); print(p.split('/')[-2], "total runs,followed,followed|quoted,flagged,quoted:", tot); [print("   ",k,v) for k,v in by.items()]
