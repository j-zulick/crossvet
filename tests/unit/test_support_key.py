"""The support-check answer key and crossvet-bench support-key, with a stand-in checker."""

import argparse
import json

import pytest

from open_deep_research import bench
from open_deep_research.support_key import CASES, MODES, evaluate


class Oracle:
    """Says 0.9 for supported cases and 0.1 otherwise; optionally fails on some claims."""

    model = "oracle"

    def __init__(self, invert: bool = False, fail: tuple[str, ...] = ()):
        self.invert, self.fail, self.errors = invert, fail, 0
        self.answers = {(c.finding, c.passage): c.supported for c in CASES}
        self.answers |= {(c.fact, c.passage): c.supported for c in CASES}

    async def check(self, pairs):
        out = []
        for claim, passage in pairs:
            if any(f in claim for f in self.fail):
                out.append(None)
                continue
            yes = self.answers[(claim, passage)] != self.invert
            out.append(0.9 if yes else 0.1)
        return out


def test_key_is_balanced_and_well_formed():
    assert len(CASES) == 24 and sum(c.supported for c in CASES) == 12
    assert len({c.id for c in CASES}) == len(CASES)
    assert {c.kind for c in CASES if not c.supported} == {"misread", "same_topic", "partial", "contradicts"}
    assert all(c.finding != c.fact for c in CASES)


@pytest.mark.parametrize("mode", MODES)
def test_perfect_and_inverted_checkers(mode):
    good = evaluate(Oracle(), mode)
    assert good["accuracy"] == 1.0 and good["balanced_accuracy"] == 1.0 and good["rejection_rate"] == 0.5
    bad = evaluate(Oracle(invert=True), mode)
    assert bad["accuracy"] == 0.0 and bad["supported_accepted"] == 0.0


def test_failed_calls_count_as_unsupported_and_are_reported():
    r = evaluate(Oracle(fail=("27.1%",)), "fact")
    assert r["errors"] > 0 and r["supported_accepted"] < 1.0


def test_bad_mode():
    with pytest.raises(ValueError):
        evaluate(Oracle(), "draft")


def test_cli_dry_run_and_run(tmp_path, capsys):
    args = argparse.Namespace(mode="both", min_prob=0.5, model="", dry_run=True, out="")
    assert bench._support_key(args) == 0
    assert "48 Jev calls" in capsys.readouterr().out
    out = tmp_path / "key.json"
    args = argparse.Namespace(mode="fact", min_prob=0.5, model="", dry_run=False, out=str(out))
    assert bench._support_key(args, checker=Oracle()) == 0
    data = json.loads(out.read_text())
    assert data["model"] == "oracle" and data["results"][0]["accuracy"] == 1.0
