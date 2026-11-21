"""Scan saved pages with crossvet-scan's channel check; one JSON line per page.

Run from a Crossvet checkout:  PYTHONPATH=src python chanscan.py PAGES_DIR OUT.jsonl
PAGES_DIR holds index.jsonl ({"url", "sha"} per line) and <sha>.html files.
"""
import json
import os
import signal
import sys
import time

from open_deep_research.scan_cli import scan_text


class Timeout(Exception):
    pass


def _alarm(*_):
    raise Timeout


signal.signal(signal.SIGALRM, _alarm)
pages, out_path = sys.argv[1], sys.argv[2]
seen = set()
with open(out_path, "w") as out:
    for line in open(os.path.join(pages, "index.jsonl")):
        r = json.loads(line)
        if not r.get("sha") or r["url"] in seen:
            continue
        seen.add(r["url"])
        path = os.path.join(pages, r["sha"] + ".html")
        if not os.path.exists(path):
            continue
        html = open(path, errors="ignore").read()
        start = time.time()
        signal.alarm(20)
        try:
            res = scan_text(r["url"], html)
            row = {"url": r["url"], "findings": [[f.channel, f.kinds, f.excerpt] for f in res.findings]}
        except Timeout:
            row = {"url": r["url"], "timeout": True}
        finally:
            signal.alarm(0)
        row["seconds"] = round(time.time() - start, 2)
        out.write(json.dumps(row) + "\n")
