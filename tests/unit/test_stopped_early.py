"""Replies cut short by an output limit or a provider's content filter are never treated as finished.

Found in a live pilot (Nov 17, 2026): gpt-5.4-mini stopped a report mid-quote of a statute with
``finish_reason: content_filter``, after 881 characters and before the Sources section.
"""
import asyncio

from langchain_core.messages import AIMessage

from open_deep_research import deep_researcher as dr
from open_deep_research.models import stop_problem, stopped_by_filter

FULL = "# Report\n\nThe mandate is set by statute [1].\n\n### Sources\n[1] https://a.example/law\n"
CUT = "# Report\n\nThe Act says: > “The Board shall maintain long run growth of the monetary and"


def msg(text, **meta):
    return AIMessage(content=text, response_metadata=meta)


def test_stopped_by_filter_reads_every_provider_signal():
    assert stopped_by_filter(msg("x", finish_reason="content_filter"))            # OpenAI
    assert stopped_by_filter(msg("x", stop_reason="refusal"))                     # Anthropic
    assert stopped_by_filter(msg("x", finish_reason="RECITATION"))                # Google
    assert stopped_by_filter(msg("x", incomplete_details={"reason": "content_filter"}))  # Responses API
    assert not stopped_by_filter(msg("x", finish_reason="stop"))
    assert not stopped_by_filter(msg("x"))


def test_stop_problem_names_the_reason():
    assert stop_problem(msg("x", finish_reason="length")) == "it stopped at the output limit"
    assert stop_problem(msg("x", finish_reason="content_filter")) == "a provider content filter stopped it"
    assert stop_problem(msg("x", finish_reason="stop")) == ""


class Writer:
    """Fake report model that returns scripted replies in order and records prompts."""

    def __init__(self, replies):
        self.replies, self.prompts = list(replies), []

    async def ainvoke(self, messages, *a, **k):
        self.prompts.append(messages[0].content)
        return self.replies.pop(0)


def run_writer(monkeypatch, replies):
    writer = Writer(replies)
    monkeypatch.setattr(dr, "stage_model", lambda cfg, shape=None: writer)
    out = asyncio.run(dr.final_report_generation(
        {"notes": ["Note: the mandate is set by statute. https://a.example/law"], "messages": [], "research_brief": "b"},
        {"configurable": {}},
    ))
    return out, writer


def test_a_filtered_report_is_written_again_with_paraphrase(monkeypatch):
    out, writer = run_writer(monkeypatch, [msg(CUT, finish_reason="content_filter"), msg(FULL, finish_reason="stop")])
    assert out["final_report"] == FULL
    assert len(writer.prompts) == 2 and "Paraphrase sources" in writer.prompts[1]


def test_a_report_that_stops_early_twice_says_so(monkeypatch):
    out, _ = run_writer(monkeypatch, [msg(CUT, finish_reason="content_filter"), msg(CUT + " credit", finish_reason="content_filter")])
    assert out["final_report"].startswith(CUT + " credit")
    assert "**Incomplete report:**" in out["final_report"] and "content filter" in out["final_report"]


def test_a_finished_report_is_not_retried(monkeypatch):
    out, writer = run_writer(monkeypatch, [msg(FULL, finish_reason="stop")])
    assert out["final_report"] == FULL and len(writer.prompts) == 1


def test_deep_agent_flags_a_report_written_by_a_filtered_reply():
    from open_deep_research.deep_agent import REPORT_PATH, report_stop_problem

    write = AIMessage(content="", tool_calls=[{"name": "write_file", "args": {"file_path": REPORT_PATH, "content": CUT}, "id": "1"}],
                      response_metadata={"finish_reason": "content_filter"})
    done = AIMessage(content="Report written.", response_metadata={"finish_reason": "stop"})
    assert report_stop_problem({"messages": [write, done]}) == "a provider content filter stopped it"
    ok = AIMessage(content="", tool_calls=[{"name": "write_file", "args": {"file_path": REPORT_PATH, "content": FULL}, "id": "2"}],
                   response_metadata={"finish_reason": "stop"})
    assert report_stop_problem({"messages": [ok, done]}) == ""
    assert report_stop_problem({"messages": [msg("cut", finish_reason="length")]}) == "it stopped at the output limit"
