"""Posts from folders and URL lists, repeated claims merged, conflicts shown, and what each post would change."""

from __future__ import annotations

import json

from open_deep_research.chat import cli
from open_deep_research.chat.tuning import (
    Evidence,
    claim_key,
    conflicts,
    group_evidence,
)

POST_A = "After a month of tests, openai:big is the best at code I have tried. It fixed a race nobody else caught."
POST_B = "Our team agrees: openai:big is the best at code I have tried, and it is quick too. Nothing else came close."
POST_C = "Unpopular opinion, but openai:big is weak at code for us: it misses edge cases in every review we ran."


def claims_for(models, *claims):
    models.set("openai:mid", *[json.dumps({"claims": c}) for c in claims])


def good(quote):
    return [{"model": "openai:big", "vendor": "openai", "kind": "code", "verdict": "good", "quote": quote}]


def bad(quote):
    return [{"model": "openai:big", "vendor": "openai", "kind": "code", "verdict": "bad", "quote": quote}]


def ev(i, model="openai:big", verdict="good", kind="code", model_id=""):
    return Evidence(i, "s", kind, model, model_id, "openai", verdict, "q")


def test_claims_are_the_same_by_kind_model_and_verdict():
    assert claim_key(ev(1, "openai:big")) == claim_key(ev(2, "OpenRouter:OpenAI/Big ")) == claim_key(ev(3, "big"))
    assert claim_key(ev(1, "gpt 6 sol")) == claim_key(ev(2, "gpt_6_sol"))
    assert claim_key(ev(1, model_id="openai/gpt-x")) == claim_key(ev(2, model_id="gpt-x"))
    groups = group_evidence([ev(3), ev(1), ev(2, verdict="bad")])
    assert [[e.id for e in g] for g in groups] == [[1, 3], [2]]
    assert conflicts([ev(1), ev(2, verdict="bad"), ev(3, kind="writing")]) == {1: [2], 2: [1]}


def setup(tmp_path, monkeypatch, hub):
    monkeypatch.setattr(cli, "_hub", lambda: hub)
    folder = tmp_path / "posts"
    folder.mkdir()
    (folder / "a.txt").write_text(POST_A)
    (folder / "b.md").write_text(POST_B)
    (folder / "skip.pdf").write_text("not read")
    return folder


def test_a_folder_imports_every_post_and_says_what_each_would_change(hub, models, tmp_path, monkeypatch, capsys):
    folder = setup(tmp_path, monkeypatch, hub)
    claims_for(models, good("openai:big is the best at code I have tried"), good("openai:big is the best at code I have tried"))
    assert cli.main(["routes", "import", str(folder)]) == 0
    out = capsys.readouterr().out
    assert "a.txt: imported, 1 claim(s) kept" in out and "b.md: imported, 1 claim(s) kept" in out and "skip.pdf" not in out
    assert "would put openai:big first for code" in out
    assert "repeats #1" in out and "posts: 2 imported" in out


def test_repeated_claims_show_once_and_are_accepted_together(hub, models, tmp_path, monkeypatch, capsys):
    folder = setup(tmp_path, monkeypatch, hub)
    claims_for(models, good("openai:big is the best at code I have tried"), good("openai:big is the best at code I have tried"))
    cli.main(["routes", "import", str(folder)])
    capsys.readouterr()
    assert cli.main(["routes", "evidence"]) == 0
    out = capsys.readouterr().out
    assert out.count("is GOOD") == 1 and "same claim: #2; 2 sources" in out
    versions = len(hub.tuning.history())
    assert cli.main(["routes", "accept", "1"]) == 0
    out = capsys.readouterr().out
    assert "also accepted the same claim from other posts: #2" in out
    assert len(hub.tuning.history()) == versions + 1  # one table change, not two
    assert {e.id: e.status for e in hub.tuning.evidence()} == {1: "accepted", 2: "accepted"}


def test_one_decides_only_that_claim(hub, models, tmp_path, monkeypatch, capsys):
    folder = setup(tmp_path, monkeypatch, hub)
    claims_for(models, good("openai:big is the best at code I have tried"), good("openai:big is the best at code I have tried"))
    cli.main(["routes", "import", str(folder)])
    assert cli.main(["routes", "reject", "1", "--one"]) == 0
    assert {e.id: e.status for e in hub.tuning.evidence()} == {1: "rejected", 2: "pending"}


def test_conflicting_posts_are_flagged(hub, models, tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(cli, "_hub", lambda: hub)
    a, c = tmp_path / "a.txt", tmp_path / "c.txt"
    a.write_text(POST_A)
    c.write_text(POST_C)
    claims_for(models, good("openai:big is the best at code I have tried"), bad("openai:big is weak at code for us"))
    assert cli.main(["routes", "import", str(a), str(c)]) == 0
    assert "contradicts #1" in capsys.readouterr().out
    assert cli.main(["routes", "evidence"]) == 0
    assert "conflicts with #2 (the opposite verdict)" in capsys.readouterr().out


def test_a_url_list_file_is_read(hub, models, tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(cli, "_hub", lambda: hub)
    post = tmp_path / "a.txt"
    post.write_text(POST_A)
    listing = tmp_path / "urls.txt"
    listing.write_text(f"# my reading list\n{post}\n\n")
    claims_for(models, good("openai:big is the best at code I have tried"))
    assert cli.main(["routes", "import", "--urls", str(listing)]) == 0
    assert f"{post}: imported, 1 claim(s) kept" in capsys.readouterr().out


def test_import_with_nothing_to_read_explains_usage(hub, monkeypatch, capsys):
    monkeypatch.setattr(cli, "_hub", lambda: hub)
    assert cli.main(["routes", "import"]) == 2
    assert "usage: crossvet chat routes import" in capsys.readouterr().err
