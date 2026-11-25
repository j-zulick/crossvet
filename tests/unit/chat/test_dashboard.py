"""The dashboard: numbers from the store, one self-contained page (offline)."""

from __future__ import annotations

import re

from crossvet.chat import cli, dashboard
from crossvet.chat.providers import Reply


def test_dashboard_numbers_come_from_the_store(hub, models, tmp_path, monkeypatch, capsys):
    models.set("openai:small", Reply(text="ok", model="openai:small", input_tokens=1000, output_tokens=10,
                                     extra={"cached_tokens": 250}, cost=0.002))
    a = hub.ask("Translate to French: hello")
    hub.feedback(True, turn_id=a.turn_id)
    b = hub.ask("Translate to French: goodbye")
    hub.feedback(False, turn_id=b.turn_id)
    numbers = dashboard.data(hub, 7)
    assert numbers["answers"] == 2 and numbers["spend"] == 0.004 and numbers["good_rate"] == 0.5
    assert numbers["cached_share"] == 0.25 and numbers["answers_per_model"] == {"openai:small": 2}
    page = dashboard.page(numbers)
    assert "$0.0040" in page and "50%" in page and "translate (2)" in page and "<title>openai:small: 2</title>" in page
    assert not re.search(r"(src|href)=[\"']https?://", page)  # no outside resources
    monkeypatch.setattr(cli, "_hub", lambda: hub)
    assert cli.main(["dashboard", "--out", str(tmp_path / "d.html"), "--days", "7"]) == 0
    assert (tmp_path / "d.html").read_text().startswith("<!doctype html>") and "2 answers" in capsys.readouterr().out


def test_an_empty_store_says_so(hub):
    page = dashboard.page(dashboard.data(hub, 7))
    assert page.count("No data yet.") == 4 and ">-<" in page
