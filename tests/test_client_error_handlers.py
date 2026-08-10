"""Client.ask_error_handlers: the client-wide fallback for ask()'s
error_handlers, plus register_ask_error_handler()/unregister_ask_error_handler().

_handle_ask_error() is the exact function ask()'s except block calls, so
matching and precedence are tested by calling it directly rather than by
reimplementing its routing logic in the test.
"""

import pyroflow
import pytest

from pyroflow.client import _handle_ask_error


class ExcA(Exception):
    pass


class ExcB(Exception):
    pass


# --- _handle_ask_error(): matching -------------------------------------------


async def test_matching_handler_runs_and_reports_true():
    calls = []

    async def handler(exc, m):
        calls.append((exc, m))

    ran = await _handle_ask_error(ExcA(), "the message", {ExcA: handler}, {})
    assert ran is True
    assert len(calls) == 1 and calls[0][1] == "the message"


async def test_non_matching_handler_does_not_run():
    calls = []

    async def handler(exc, m):
        calls.append(exc)

    ran = await _handle_ask_error(ExcA(), "m", {ExcB: handler}, {})
    assert ran is False
    assert calls == []


@pytest.mark.parametrize("call_handlers", [{}, None])
async def test_empty_or_missing_mapping_is_a_noop(call_handlers):
    assert await _handle_ask_error(ExcA(), "m", call_handlers, {}) is False


async def test_tuple_key_matches_any_listed_type():
    calls = []

    async def handler(exc, m):
        calls.append(exc)

    ran = await _handle_ask_error(ExcA(), "m", {(ExcB, ExcA): handler}, {})
    assert ran is True and len(calls) == 1


async def test_sync_handler_is_supported():
    calls = []

    def handler(exc, m):
        calls.append(exc)

    ran = await _handle_ask_error(ExcA(), "m", {ExcA: handler}, {})
    assert ran is True and len(calls) == 1


# --- _handle_ask_error(): call-vs-client precedence -------------------------


async def test_call_level_handler_wins_over_an_identical_client_key():
    calls = []
    call_handlers = {ExcA: lambda exc, m: calls.append("call")}
    client_handlers = {ExcA: lambda exc, m: calls.append("client")}

    await _handle_ask_error(ExcA(), "m", call_handlers, client_handlers)

    assert calls == ["call"]


async def test_call_level_handler_wins_over_a_broader_client_handler():
    """The bug this guards: a naive `{**client, **call}` merge lets whichever
    key a dict happens to order first win — not necessarily the call's — for
    keys that overlap by subclassing rather than by being identical. A
    client-wide Exception fallback must not shadow a call's more specific
    handler."""
    calls = []
    call_handlers = {ExcA: lambda exc, m: calls.append("call-specific")}
    client_handlers = {Exception: lambda exc, m: calls.append("client-broad")}

    await _handle_ask_error(ExcA("boom"), "m", call_handlers, client_handlers)

    assert calls == ["call-specific"], (
        "client's broader handler ran instead of the call's specific one"
    )


async def test_client_handler_runs_only_when_the_call_had_no_match():
    calls = []
    call_handlers = {ExcB: lambda exc, m: calls.append("call")}
    client_handlers = {ExcA: lambda exc, m: calls.append("client")}

    await _handle_ask_error(ExcA("boom"), "m", call_handlers, client_handlers)

    assert calls == ["client"]


async def test_client_handler_runs_when_the_call_passed_none():
    calls = []
    client_handlers = {ExcA: lambda exc, m: calls.append("client")}

    await _handle_ask_error(ExcA("boom"), "m", None, client_handlers)

    assert calls == ["client"]


async def test_neither_mapping_matching_reports_false():
    ran = await _handle_ask_error(ExcA("boom"), "m", {ExcB: lambda e, m: None}, {})
    assert ran is False


# --- Client.ask_error_handlers attribute ------------------------------------


def make_client():
    return pyroflow.Client("probe", api_id=1, api_hash="x", in_memory=True)


def test_ask_error_handlers_starts_empty():
    assert make_client().ask_error_handlers == {}


def test_ask_error_handlers_is_not_shared_between_instances():
    """The classic mutable-default trap: each Client must get its own dict,
    not one every instance ends up sharing."""
    a, b = make_client(), make_client()
    a.ask_error_handlers[ExcA] = "handler"
    assert b.ask_error_handlers == {}


# --- register_ask_error_handler() / unregister_ask_error_handler() ---------


def test_register_ask_error_handler_adds_an_entry():
    c = make_client()
    handler = lambda exc, m: None

    c.register_ask_error_handler(ExcA, handler)

    assert c.ask_error_handlers == {ExcA: handler}


def test_register_ask_error_handler_replaces_an_existing_entry():
    """No ValueError on re-registering — unlike register_listener() and
    friends, this has no dispatcher lifecycle or duplicate check."""
    c = make_client()
    first = lambda exc, m: None
    second = lambda exc, m: None

    c.register_ask_error_handler(ExcA, first)
    c.register_ask_error_handler(ExcA, second)

    assert c.ask_error_handlers == {ExcA: second}


def test_register_ask_error_handler_accepts_a_tuple_key():
    c = make_client()
    handler = lambda exc, m: None

    c.register_ask_error_handler((ExcA, ExcB), handler)

    assert c.ask_error_handlers == {(ExcA, ExcB): handler}


def test_unregister_ask_error_handler_removes_an_entry_and_reports_true():
    c = make_client()
    c.register_ask_error_handler(ExcA, lambda exc, m: None)

    removed = c.unregister_ask_error_handler(ExcA)

    assert removed is True
    assert c.ask_error_handlers == {}


def test_unregister_ask_error_handler_reports_false_when_nothing_registered():
    c = make_client()
    assert c.unregister_ask_error_handler(ExcA) is False


def test_unregister_ask_error_handler_requires_the_exact_key():
    """A tuple key is not decomposed: registering (ExcA, ExcB) and then
    unregistering plain ExcA must not remove it."""
    c = make_client()
    c.register_ask_error_handler((ExcA, ExcB), lambda exc, m: None)

    removed = c.unregister_ask_error_handler(ExcA)

    assert removed is False
    assert len(c.ask_error_handlers) == 1
