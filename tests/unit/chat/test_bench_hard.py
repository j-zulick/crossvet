"""The hard chat-benchmark suite: every answer key holds, and each trap costs points (offline)."""

from __future__ import annotations

import pytest

from crossvet.chat import bench, cli

HARD = {c.name: c for c in bench.HARD_CASES}


def test_every_hard_case_has_a_reference_answer_that_scores_one():
    assert {c.kind for c in bench.HARD_CASES} == {"quick", "summarize", "extract", "writing", "reasoning", "code", "long"}
    for case in bench.HARD_CASES:
        assert case.example, case.name
        assert case.score(case.example) == pytest.approx(1.0), case.name


def test_reference_code_passes_its_checks_when_run():
    for case in bench.HARD_CASES:
        if hasattr(case.score, "checks"):
            assert bench.run_code_score(case.example, case.score.function_name, case.score.checks) == 1.0, case.name


@pytest.mark.parametrize(("name", "trap"), [
    ("count-letters", "5"),
    ("decimal-compare", "9.11"),
    ("corrected-figure", "Sarasota Ford's own site appeared in five of six searches, the only dealer site that ranked."),
    ("corrected-listing", '{"year": 2016, "make": "Nissan", "model": "Rogue", "trim": "SV", "price": 11949, "miles": 45585}'),
    ("directory-dealers", '{"dealers": ["Sarasota Ford", "Gettel Hyundai of Sarasota", "Scotti\'s Auto", "Gulf Coast Auto Brokers of Sarasota"]}'),
    ("directory-dealers", '{"dealers": ["Scotti\'s Auto", "Gettel Hyundai of Sarasota", "Gulf Coast Auto Brokers of Sarasota"]}'),  # wrong order
    ("three-bullets", "- New price from 1 May!\n- It was $12.\n- It will be $15.\n- Thanks for staying with us."),
    ("plain-english", "We will leverage what we have to deliver faster."),
    ("time-zones", "It starts at 07:30 the next morning in Tokyo."),
    ("pumps", "The third pump needs 4 hours."),
    ("price-back", "The original price was $96."),
    ("search-order", "The second fewest is Edmunds."),
    ("long-log", "The draft tally was 5."),
    ("long-log", "TrueCar appeared in 3."),
])
def test_traps_score_below_one(name, trap):
    assert HARD[name].score(trap) < 1.0


def test_naming_the_wrong_answer_then_the_right_one_counts_the_right_one():
    assert HARD["search-order"].score("Not Cars.com: it is TrueCar.") == 1.0
    assert HARD["time-zones"].score("Not 05:30 but 6:30.") == 1.0


def test_a_number_written_as_a_word_counts():
    # 2026-11-25 live run: two models wrote "under six years old" and lost a third of the score.
    gold = next(c for c in bench.CASES if c.name == "gold-certified")
    assert gold.score("A Gold certified vehicle must pass a 172-point inspection, be under six years old, and have fewer than 80,000 miles.") == 1.0
    assert gold.score("A Gold certified vehicle must pass a 172-point inspection and have fewer than 80,000 miles.") < 1.0


def test_typographic_quotes_match_plain_ones():
    assert bench._same("Scotti\u2019s Auto", "Scotti's Auto")
    curly = '{"dealers": ["Gettel Hyundai of Sarasota", "Scotti\u2019s Auto", "Gulf Coast Auto Brokers of Sarasota"]}'
    assert HARD["directory-dealers"].score(curly) == 1.0


def test_a_listing_with_year_and_make_in_their_own_keys_scores_full():
    # 2026-11-25 live run: all six models wrote "model": "2016 Nissan Rogue" when the prompt had no year or make key.
    good = '{"year": 2016, "make": "Nissan", "model": "Rogue", "trim": "SV", "price": 11994, "miles": 45558}'
    assert HARD["corrected-listing"].score(good) == 1.0


def test_numbers_in_json_match_however_they_are_written():
    assert bench._same(1480.5, "1480.50") and bench._same("2,310.00", "2310") and not bench._same("INV-1", "INV-2")


def test_the_long_case_is_long_and_holds_one_answer_and_two_traps():
    prompt = HARD["long-log"].prompt
    assert len(prompt.split()) > 8000

    assert "Recount of Sarasota Ford's own site across the six searches: 4" in prompt
    assert "First tally of Sarasota Ford's own site across the six searches: 5" in prompt and "TrueCar across the six searches: 3" in prompt


def test_the_search_data_matches_the_recount():
    from collections import Counter

    seen = Counter(site for sites in bench.SEARCH_SITES.values() for site in sites)
    assert len(bench.SEARCH_SITES) == 6
    assert (seen["Kelley Blue Book"], seen["iSeeCars"], seen["Sarasota Ford"], seen["Edmunds"], seen["TrueCar"]) == (5, 5, 4, 4, 3)


def test_the_suite_option_picks_the_cases(hub, monkeypatch, capsys):
    monkeypatch.setattr(cli, "_hub", lambda: hub)
    assert cli.main(["bench", "-m", "openai:small", "--suite", "hard", "--dry-run"]) == 0
    assert f"{len(bench.HARD_CASES)} hard cases" in capsys.readouterr().out
    assert cli.main(["bench", "-m", "openai:small", "--dry-run"]) == 0
    assert f"{len(bench.CASES)} standard cases" in capsys.readouterr().out


def test_best_value_fills_the_long_slot_only_when_long_cases_ran():
    rows = [{"model": "google:wide", "case": "long-log", "kind": "long", "score": 1.0, "cost": 0.02, "error": ""},
            {"model": "openai:small", "case": "long-log", "kind": "long", "score": 0.0, "cost": 0.001, "error": ""},
            {"model": "openai:small", "case": "zip", "kind": "quick", "score": 1.0, "cost": 0.0001, "error": ""}]
    slots = bench.best_value(rows)
    assert slots["long"] == ["google:wide"] and "long" not in bench.best_value(rows[2:])


def test_the_table_marks_kinds_a_model_was_not_asked():
    rows = [{"model": "google:wide", "case": "long-log", "kind": "long", "score": 1.0, "cost": None, "error": ""},
            {"model": "openai:small", "case": "zip", "kind": "quick", "score": 1.0, "cost": None, "error": ""}]
    lines = bench.table(rows).splitlines()
    assert lines[1].startswith("long") and "-" in lines[1].split()[1:]


ROWS = [
    {"model": "openai:small", "case": "zip", "kind": "quick", "score": 1.0, "cost": 0.0001, "error": ""},
    {"model": "openai:small", "case": "trains", "kind": "reasoning", "score": 0.0, "cost": 0.0002, "error": ""},
    {"model": "anthropic:big", "case": "zip", "kind": "quick", "score": 1.0, "cost": 0.002, "error": ""},
    {"model": "anthropic:big", "case": "trains", "kind": "reasoning", "score": 0.0, "cost": None, "error": "HTTP 529"},
]


def test_the_results_page_holds_only_numbers_from_the_rows():
    import re

    page = bench.results_page(ROWS, date="2026-12-01", suite="standard", command="crossvet chat bench -m a")
    assert "2 cases, 4 calls, 1 failed" in page and "$0.0023 for the 3 of 4 calls that reported one" in page
    assert "`anthropic:big` on `trains`: HTTP 529" in page and "`quick`: `openai:small`, `anthropic:big`" in page
    allowed = {"2026", "12", "01", "2", "4", "1", "0", "3", "10", "0.0023", "529"} | set(re.findall(r"\d+\.\d+", bench.table(ROWS)))
    prose = page.split("```")[0] + page.split("```")[2]  # the table between the fences is checked by `table`'s own tests
    assert set(re.findall(r"\d+(?:\.\d+)?", prose)) <= allowed


def test_bench_page_option_writes_the_page_and_the_rows(hub, monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(cli, "_hub", lambda: hub)
    monkeypatch.setattr(bench, "run", lambda *a, **k: ROWS)
    assert cli.main(["bench", "-m", "openai:small", "-m", "anthropic:big", "--page", str(tmp_path / "run")]) == 0
    page = (tmp_path / "run" / "README.md").read_text()
    assert "# Chat benchmark, " in page and "-m openai:small -m anthropic:big --suite standard" in page
    assert len((tmp_path / "run" / "results.jsonl").read_text().splitlines()) == 4
