"""Tests for building MLX LoRA datasets from run exports (offline)."""

import asyncio
import json

from langchain_core.messages import HumanMessage

from open_deep_research import dataset, deep_researcher

from .test_end_to_end import SOURCE_URL, scripted  # noqa: F401  (pytest fixture)

NOTES = f"Source: {SOURCE_URL}\nSolar additions grew strongly in 2025."
DRAFT = f"# Solar\nGrew strongly [1].\n### Sources\n[1] {SOURCE_URL}\n"


def record(**over):
    base = {
        "schema_version": 2,
        "exported_at": "2026-11-07T00:00:00+00:00",
        "research_brief": "How much solar capacity was added in 2025?",
        "research_notes": NOTES,
        "draft_report": DRAFT,
        "revised_report": DRAFT.replace("Grew strongly", "Grew strongly (figure pending)"),
        "revision_ok": True,
        "revision_feedback": "[C1, score 2.00]\n...",
        "labels": {"C1": "anthropic:b", "C2": "openai:a"},
        "critiques": {
            "anthropic:b": {"unsupported_claims": ["Not quantified"], "factual_concerns": [], "missing_perspectives": [], "suggested_revisions": ["Add the figure"], "overall_score": 6},
            "openai:a": {"unsupported_claims": [], "factual_concerns": [], "missing_perspectives": [], "suggested_revisions": [], "overall_score": 8},
        },
        "ballots": [{"ranking": ["C1", "C2"], "confidence": 0.9}, {"ranking": ["C1", "C2"], "confidence": 0.7}],
        "tally": [["C1", 3.2], ["C2", 1.6]],
    }
    base.update(over)
    return base


def test_critique_example_uses_top_voted_critique():
    ex, reason = dataset.critique_example(record())
    assert reason == ""
    roles = [m["role"] for m in ex["messages"]]
    assert roles == ["system", "user", "assistant"]
    assert NOTES in ex["messages"][1]["content"] and DRAFT in ex["messages"][1]["content"]
    assert json.loads(ex["messages"][2]["content"])["unsupported_claims"] == ["Not quantified"]


def test_critique_skips():
    assert dataset.critique_example(record(research_notes=None))[1].startswith("no research notes")
    assert dataset.critique_example(record(ballots=[{}]))[1] == "fewer than two ballots"
    assert dataset.critique_example(record(tally=[["C2", 2.0]]))[1] == "top-voted critique is empty"


def test_revise_example_and_filters():
    ex, _ = dataset.revise_example(record())
    assert ex["messages"][2]["content"].startswith("# Solar")
    assert dataset.revise_example(record(revision_ok=False))[1] == "revision failed"
    bad = record(revised_report=DRAFT + "[2] https://made.up/page\n")
    assert dataset.revise_example(bad)[1] == "revised report cites URLs the research never read"


def test_split_is_deterministic_and_by_brief():
    assert dataset.split_for("Q one") == dataset.split_for("  q ONE ")
    counts = {s: 0 for s in ("train", "valid", "test")}
    for i in range(2000):
        counts[dataset.split_for(f"question {i}")] += 1
    assert 1450 < counts["train"] < 1750 and 120 < counts["valid"] < 290 and 120 < counts["test"] < 290


def test_build_dedupes_and_writes(tmp_path):
    runs = [record(), record(), record(research_brief="Another question?"), {"garbage": True}]
    splits, skipped = dataset.build(runs, "critique")
    assert sum(len(v) for v in splits.values()) == 2
    assert skipped["duplicate"] == 1 and skipped["no research notes in export (needs schema_version 2)"] == 1
    dataset.write(splits, tmp_path)
    assert sorted(p.name for p in tmp_path.iterdir()) == ["test.jsonl", "train.jsonl", "valid.jsonl"]


def test_cli_reads_malformed_lines(tmp_path, capsys):
    runs = tmp_path / "runs.jsonl"
    runs.write_text(json.dumps(record()) + "\nnot json\n\n")
    code = dataset.main(["--runs", str(runs), "--task", "critique", "--out", str(tmp_path / "out")])
    assert code == 0 and "critique: 1 examples" in capsys.readouterr().out


def test_real_export_round_trip(scripted, monkeypatch, tmp_path):  # noqa: F811
    """A reviewed run exported by the real graph converts into a critique example."""
    export = tmp_path / "runs.jsonl"
    monkeypatch.setenv("CROSS_VENDOR_REVIEW_ENABLED", "true")
    monkeypatch.setenv("REVIEW_MODELS", "openai:a,anthropic:b")
    monkeypatch.setenv("RUN_EXPORT_PATH", str(export))
    asyncio.run(deep_researcher.deep_researcher.ainvoke({"messages": [HumanMessage(content="How much solar capacity was added in 2025?")]}))
    rec = next(dataset.read_runs(export))
    assert rec["schema_version"] == 2 and SOURCE_URL in rec["research_notes"]
    ex, reason = dataset.critique_example(rec)
    assert reason == "" and ex["messages"][2]["role"] == "assistant"
