"""Second-vendor review: findings are checked against the diff in code; fixes are checked by git; the benchmark."""

from __future__ import annotations

import json
import subprocess

import pytest

from crossvet import cli, mcp_server, review, review_bench

DIFF = """diff --git a/src/app/cap.py b/src/app/cap.py
--- a/src/app/cap.py
+++ b/src/app/cap.py
@@ -10,4 +10,5 @@ def check(spent, cap):
     total = spent
-    if total >= cap:
+    if total > cap * 2:
+        log(total)
         raise Stop()
     return total
"""
TASK = "Stop calls once spend reaches the cap."


@pytest.fixture(autouse=True)
def _keys(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "x")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "x")


def finding(**over):
    return {"file": "src/app/cap.py", "line": 11, "severity": "major", "quote": "total > cap * 2",
            "problem": "The cap stops at twice its value.", "fix": "Use total >= cap.", **over}


def test_the_diff_is_read_on_the_new_side():
    files = review.parse_diff(DIFF)
    assert list(files) == ["src/app/cap.py"]
    assert files["src/app/cap.py"].lines == {10: "    total = spent", 11: "    if total > cap * 2:", 12: "        log(total)",
                                            13: "        raise Stop()", 14: "    return total"}
    assert files["src/app/cap.py"].added == {11, 12}


@pytest.mark.parametrize(("change", "reason"), [
    ({}, ""),
    ({"file": "b/src/app/cap.py"}, ""),
    ({"severity": "critical"}, "severity"),
    ({"file": "src/app/other.py"}, "not in the diff"),
    ({"line": 40}, "not a line the diff shows"),
    ({"quote": "total >= cap"}, "quote is not on line 11"),
    ({"quote": ""}, "quotes nothing"),
    ({"quote": "total", "line": 13}, "quote is not on line 13"),  # "total" is on 10, 11 and 12: no single line to move to
    ({"problem": ""}, "names no problem"),
    ({"line": "eleven"}, "not a line"),
])
def test_each_finding_is_checked_in_code(change, reason):
    checked = review.check(finding(**change), review.parse_diff(DIFF))
    assert (checked.dropped == "") if not reason else (reason in checked.dropped)


def test_a_quote_on_one_nearby_line_moves_the_finding_there():
    checked = review.check(finding(line=13), review.parse_diff(DIFF))
    assert checked.dropped == "" and checked.line == 11 and checked.moved_from == 13
    assert review.check(finding(line=30), review.parse_diff(DIFF)).dropped  # too far away


def test_a_review_uses_another_vendor_and_keeps_only_what_holds(make, fake, tmp_path):
    cv = make(slots={"reviewer": ["openai:gpt-6.1-sol", "anthropic:claude-opus-5-5"]})
    fake.on("anthropic:claude-opus-5-5", json.dumps({"findings": [finding(), finding(line=99, problem="made up")]}))
    result = review.run(cv, DIFF, TASK, author="openai:gpt-6.1-sol", record_dir=tmp_path)
    assert result.reviewer == "anthropic:claude-opus-5-5"  # not the author's vendor, though sol is first in the slot
    assert [(f.file, f.line) for f in result.kept] == [("src/app/cap.py", 11)]
    assert "not a line the diff shows" in result.findings[1].dropped
    assert "Dropped by the checks" in open(result.record).read()
    assert cv.lab.reviews()[0]["record"]["reviewer"] == "anthropic:claude-opus-5-5"
    assert "1 finding(s) kept, 1 dropped" in review.text(result)


def test_a_reply_that_is_not_json_keeps_nothing(make, fake):
    cv = make()
    fake.on("anthropic:claude-opus-5-5", "Looks good to me! Ship it.")
    fake.on("openai:gpt-6.1-sol", "Looks good to me! Ship it.")
    result = review.run(cv, DIFF, TASK, author="sonnet", reviewer="gpt")
    assert result.kept == [] and "did not answer with the JSON" in result.findings[0].dropped


def test_review_refuses_without_another_vendor_and_oversized_diffs(make, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY")
    with pytest.raises(ValueError, match="another vendor"):
        review.run(make(), DIFF, TASK, author="openai:gpt-6.1-sol")
    with pytest.raises(ValueError, match="limit"):
        review.run(make(), "x" * (review.MAX_DIFF + 1), TASK)


def git(cwd, *args):
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True,
                   env={"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.com", "GIT_COMMITTER_NAME": "t",
                        "GIT_COMMITTER_EMAIL": "t@example.com", "PATH": "/usr/bin:/bin", "HOME": str(cwd)})


def test_fix_writes_a_patch_git_accepts_then_reviews_again(make, fake, tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "cap.py").write_text("def check(spent, cap):\n    if spent >= cap:\n        raise Stop()\n")
    git(repo, "init", "-q")
    git(repo, "add", ".")
    git(repo, "commit", "-qm", "base")
    (repo / "cap.py").write_text("def check(spent, cap):\n    if spent > cap * 2:\n        raise Stop()\n")
    git(repo, "add", ".")
    diff = review.git_diff(staged=True, cwd=str(repo))
    assert "+    if spent > cap * 2:" in diff
    cv = make()
    bad = {"file": "cap.py", "line": 2, "severity": "major", "quote": "spent > cap * 2", "problem": "Twice the cap."}
    fake.on("openai:gpt-6.1-sol", json.dumps({"findings": [bad]}), json.dumps({"findings": []}))
    patch = ("--- a/cap.py\n+++ b/cap.py\n@@ -1,3 +1,3 @@\n def check(spent, cap):\n-    if spent > cap * 2:\n"
             "+    if spent >= cap:\n         raise Stop()\n")
    fake.on("anthropic:claude-sonnet-5-5", f"```diff\n{patch}```")
    result = review.run(cv, diff, TASK, author="sonnet", reviewer="gpt", fix=True, apply=True, rounds=2, cwd=str(repo))
    assert result.rounds[0]["applied"] and result.rounds[1]["kept"] == 0
    assert "spent >= cap" in (repo / "cap.py").read_text()
    fake.script["anthropic:claude-sonnet-5-5"] = ["not a patch"]
    fake.script["openai:gpt-6.1-sol"] = [json.dumps({"findings": [dict(bad, quote="spent > cap * 2")]})]
    refused = review.run(cv, diff, TASK, author="sonnet", reviewer="gpt", fix=True, cwd=str(repo))
    assert refused.rounds[0]["patch_applies"] is False


def test_a_bad_base_name_is_refused():
    with pytest.raises(ValueError, match="not a branch"):
        review.git_diff(base="main; rm -rf /")


def test_every_planted_case_is_a_valid_diff_with_the_bug_on_its_line():
    assert len(review_bench.CASES) == 12 and len({c.name for c in review_bench.CASES}) == 12
    for case in review_bench.CASES:
        files = review.parse_diff(case.diff())
        lines = files[case.path].lines
        assert case.line in files[case.path].added, case.name
        assert lines[case.line] == case.added[case.bug], case.name


def test_the_review_benchmark_scores_in_code(make, fake):
    cv = make()
    case = review_bench.CASES[0]
    hit = {"file": case.path, "line": case.line, "severity": "major", "quote": case.added[case.bug].strip()[:30],
           "problem": "Drops one turn."}
    fake.on("openai:gpt-6.1-sol", json.dumps({"findings": [hit]}))
    fake.on("anthropic:claude-opus-5-5", json.dumps({"findings": []}))
    rows = review_bench.run(cv, ["gpt", "claude"], review_bench.CASES[:1])
    assert [r["caught"] for r in rows] == [True, False]
    page = review_bench.results_page(rows, "crossvet bench --review -m gpt -m claude")
    assert "| `openai:gpt-6.1-sol` | 1 of 1 |" in page and "| turns-limit | off-by-one | caught | missed |" in page


def test_review_from_the_terminal_and_mcp(monkeypatch, tmp_path, fake, capsys, cv):
    from crossvet.core import Crossvet

    fake.on("openai:gpt-6.1-sol", json.dumps({"findings": [finding()]}))
    assert "1 finding(s) kept" in mcp_server.tools(cv)["review_diff"](DIFF, TASK, author_model="sonnet")
    monkeypatch.setenv("CROSSVET_DB", str(tmp_path / "chat.db"))
    real = Crossvet.__init__
    monkeypatch.setattr(Crossvet, "__init__", lambda self, *a, **k: real(self, *a, streamer=fake.stream, **k))
    monkeypatch.setattr("sys.stdin", __import__("io").StringIO(DIFF))
    assert cli.main(["review", "--task", TASK, "--json", "--no-record"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["kept"][0]["line"] == 11 and out["reviewer"] != out["author"]


def test_every_hard_case_is_cut_from_the_real_source():
    from pathlib import Path

    root = Path(__file__).resolve().parents[2]
    names = [c.name for c in review_bench.HARD]
    assert len(names) == len(set(names)) and not set(names) & {c.name for c in review_bench.CASES}
    assert sum(c.clean for c in review_bench.HARD) >= 6 and sum(not c.clean for c in review_bench.HARD) >= 12
    for case in review_bench.HARD:
        source = (root / case.path).read_text().splitlines()
        old = [*case.before, *case.removed, *case.after]
        assert source[case.start - 1: case.start - 1 + len(old)] == old, case.name
        files = review.parse_diff(case.diff())
        assert case.path in files, case.name
        if not case.clean:
            assert files[case.path].lines[case.line] == case.added[case.bug], case.name
            assert case.added != case.removed, case.name


def test_clean_changes_count_only_blocker_and_major_findings_as_false_alarms(make, fake):
    cv = make()
    clean = next(c for c in review_bench.HARD if c.clean)
    line = clean.start + len(clean.before)
    note = {"file": clean.path, "line": line, "severity": "nit", "quote": clean.added[0].strip()[:20], "problem": "Naming."}
    alarm = dict(note, severity="blocker", problem="Breaks it.")
    fake.on("openai:gpt-6.1-sol", json.dumps({"findings": [note]}))
    fake.on("anthropic:claude-opus-5-5", json.dumps({"findings": [alarm]}))
    rows = review_bench.run(cv, ["gpt", "claude"], (clean,))
    assert [r["false_alarm"] for r in rows] == [False, True] and all(r["clean"] for r in rows)
    stats = review_bench.summary(rows)
    assert stats["openai:gpt-6.1-sol"]["false_alarms"] == 0 and stats["anthropic:claude-opus-5-5"]["false_alarms"] == 1
    assert stats["openai:gpt-6.1-sol"]["cases"] == 0  # a clean change is not a bug to catch
    page = review_bench.results_page(rows, "crossvet bench --review --set hard -m gpt -m claude", "hard")
    assert "False alarms" in page and "| 1 of 1 |" in page and "1 note(s) | false alarm |" in page


def test_the_hard_set_from_the_terminal(monkeypatch, tmp_path, fake, capsys):
    from crossvet.core import Crossvet

    fake.on("openai:gpt-6.1-sol", json.dumps({"findings": []}))
    monkeypatch.setenv("CROSSVET_DB", str(tmp_path / "chat.db"))
    real = Crossvet.__init__
    monkeypatch.setattr(Crossvet, "__init__", lambda self, *a, **k: real(self, *a, streamer=fake.stream, **k))
    out = tmp_path / "bench"
    assert cli.main(["bench", "--review", "--set", "hard", "-m", "gpt", "--out", str(out)]) == 0
    page = (out / "README.md").read_text()
    assert "(hard set)" in page and "--set hard" in page
    rows = [json.loads(x) for x in (out / "results.jsonl").read_text().splitlines()]
    assert len(rows) == len(review_bench.HARD) and sum(r["clean"] for r in rows) == sum(c.clean for c in review_bench.HARD)
    assert "false alarm(s) on" in capsys.readouterr().out


def test_repeated_runs_show_which_catches_are_steady(make, fake):
    cv = make()
    case = next(c for c in review_bench.HARD if not c.clean)
    clean = next(c for c in review_bench.HARD if c.clean)
    hit = {"file": case.path, "line": case.line, "severity": "major", "quote": case.added[case.bug].strip()[:30],
           "problem": "Wrong."}
    found, nothing = json.dumps({"findings": [hit]}), json.dumps({"findings": []})
    fake.on("openai:gpt-6.1-sol", found, nothing, found, nothing, nothing, nothing)
    rows = review_bench.run(cv, ["gpt"], (case, clean), repeat=3)
    assert [r["run"] for r in rows] == [1, 2, 3, 1, 2, 3]
    stats = review_bench.summary(rows)["openai:gpt-6.1-sol"]
    assert (stats["caught"], stats["cases"], stats["always"], stats["sometimes"], stats["bugs"]) == (2, 3, 0, 1, 1)
    page = review_bench.results_page(rows, "crossvet bench --review --set hard --repeat 3 -m gpt", "hard")
    assert "each reviewer reviewed each change 3 times" in page and "Bugs caught every run" in page
    assert f"| {case.name} | {case.kind} | 2/3 |" in page and f"| {clean.name} | clean | 0/3 false alarms |" in page
    assert "3 runs per reviewer and case" in page


def test_repeat_from_the_terminal(monkeypatch, tmp_path, fake, capsys):
    from crossvet.core import Crossvet

    fake.on("openai:gpt-6.1-sol", json.dumps({"findings": []}))
    monkeypatch.setenv("CROSSVET_DB", str(tmp_path / "chat.db"))
    real = Crossvet.__init__
    monkeypatch.setattr(Crossvet, "__init__", lambda self, *a, **k: real(self, *a, streamer=fake.stream, **k))
    out = tmp_path / "bench"
    assert cli.main(["bench", "--review", "--set", "hard", "--limit", "2", "--repeat", "2", "-m", "gpt", "--out", str(out)]) == 0
    rows = [json.loads(x) for x in (out / "results.jsonl").read_text().splitlines()]
    assert len(rows) == 4 and {r["run"] for r in rows} == {1, 2}
    assert "--repeat 2" in (out / "README.md").read_text() and "bugs caught every run" in capsys.readouterr().out
