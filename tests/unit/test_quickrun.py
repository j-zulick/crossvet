"""Tests for crossvet-try (offline)."""

import json

from open_deep_research import quickrun


def test_quickrun_saves_report_review_and_share(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("REVIEW_MODELS", "openai:a,anthropic:b")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-should-never-appear")

    async def fake(question):
        return {"final_report": "# R\n\nBody.\n\n---\n\n## Review notes\n\n- Reviewed by 2 models.\n", "review": {"status": "ok", "flagged_urls": []}}

    code = quickrun.main(["What?", "--out", str(tmp_path)], invoke=fake)
    folder = next(tmp_path.iterdir())
    assert code == 0
    assert (folder / "report.md").read_text().startswith("# R")
    assert json.loads((folder / "review.json").read_text())["status"] == "ok"
    run = json.loads((folder / "run.json").read_text())
    assert run["outcome"] == "ok" and run["settings"]["REVIEW_MODELS"] == "openai:a,anthropic:b"
    share = (folder / "share.md").read_text()
    assert "Reviewed by 2 models" in share and "sk-should-never-appear" not in share
    assert "sk-should-never-appear" not in capsys.readouterr().out


def test_quickrun_records_errors(tmp_path):
    async def boom(question):
        raise RuntimeError("provider down")

    code = quickrun.main(["Q", "--out", str(tmp_path)], invoke=boom)
    folder = next(tmp_path.iterdir())
    run = json.loads((folder / "run.json").read_text())
    assert code == 1 and run["outcome"] == "error" and "provider down" in run["error"]
    assert (folder / "traceback.txt").exists()
