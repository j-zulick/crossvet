"""A provider that refuses the account (key, credit, billing) is not called again in the same process."""

from __future__ import annotations

import pytest

from crossvet.chat import providers
from crossvet.chat.providers import AccountError, ProviderError, http_error


@pytest.mark.parametrize(("status", "text"), [
    (401, "unauthorized"),
    (402, "payment required"),
    (403, '{"error": "Your credit balance is too low"}'),
    (429, '{"error": {"code": "insufficient_quota", "message": "You exceeded your current quota"}}'),
])
def test_account_refusals_are_account_errors(status, text):
    error = http_error(status, "api.example.com", text)
    assert isinstance(error, AccountError)
    assert "not called again" in str(error)


@pytest.mark.parametrize(("status", "text"), [(429, "rate limit, slow down"), (500, "oops"), (403, "region blocked")])
def test_other_failures_stay_ordinary(status, text):
    error = http_error(status, "api.example.com", text)
    assert type(error) is ProviderError


def test_a_refused_account_is_skipped_for_the_rest_of_the_session(hub, models):
    models.set("openai:small", AccountError("HTTP 429: insufficient_quota"))
    first = hub.ask("hi", slot="quick", save=False)
    assert first.model == "anthropic:small"
    assert hub.refused_accounts == {"openai"}
    calls_before = len(models.calls)
    second = hub.ask("hello again", slot="quick", save=False)
    assert second.model == "anthropic:small"
    called = [m for m, _ in models.calls[calls_before:]]
    assert all(not m.startswith("openai:") for m in called), called  # no network call to the refused account


def test_ordinary_failures_do_not_block_the_provider(hub, models):
    models.set("openai:small", ProviderError("HTTP 500 from api.openai.com"), "fine now")
    hub.ask("hi", slot="quick", save=False)
    assert hub.refused_accounts == set()
    assert hub.ask("again", slot="quick", save=False).model == "openai:small"


def test_streams_are_guarded_too(hub, models):
    models.set("openai:small", AccountError("HTTP 402"))
    list(hub.ask_stream("hi", slot="quick"))
    assert providers.account_of("openai:small") in hub.refused_accounts
