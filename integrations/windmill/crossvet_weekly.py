"""Windmill script: judge a sample of last week's answers, apply score routes if allowed, return the week's numbers.

Schedule it weekly in Windmill on a worker where `crossvet` is installed and its keys are set.
`crossvet tune auto` changes nothing unless [router] auto_tune = true in crossvet.toml.
"""

import json
import subprocess


def main(score_limit: int = 50) -> dict:
    """Run the weekly Crossvet steps and return the weekly report as a dict."""
    steps = {}
    for name, args in (("score", ["crossvet", "score", "run", "--limit", str(score_limit)]), ("tune", ["crossvet", "tune", "auto"])):
        done = subprocess.run(args, capture_output=True, text=True, timeout=1800, check=False)
        steps[name] = done.stdout.strip() or done.stderr.strip()
    report = subprocess.run(["crossvet", "report", "--week", "--json"], capture_output=True, text=True, timeout=300, check=True)
    return {"steps": steps, "week": json.loads(report.stdout)}
