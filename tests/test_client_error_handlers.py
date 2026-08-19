"""Client.ask_error_handlers: the client-wide fallback for ask()'s
error_handlers, plus register_ask_error_handler()/unregister_ask_error_handler().

handle_ask_error() is the exact function ask()'s except block calls, so
matching and precedence are tested by calling it directly rather than by
reimplementing its routing logic in the test.
"""

from types import SimpleNamespace

import pyroflow
import pytest

from pyroflow.utils import handle_ask_error
from pyroflow.types import CallbackQuery, Message


class ExcA(Exception):
    pass


class ExcB(Exception):
    pass


# --- handle_ask_error(): matching -------------------------------------------


async def test_matching_handler_runs_and_reports_true():
    calls = []

    async def handler(exc, m):
        calls.append((exc, m))

    ran = await handle_ask_error(ExcA(), "the message", {ExcA: handler}, {})
    assert ran is True
    assert len(calls) == 1 and calls[0][1] == "the message"


async def test_non_matching_handler_does_not_run():
    calls = []

    async def handler(exc, m):
        calls.append(exc)

    ran = await handle_ask_error(ExcA(), "m", {ExcB: handler}, {})
    assert ran is False
    assert calls == []


@pytest.mark.parametrize("call_handlers", [{}, None])
async def test_empty_or_missing_mapping_is_a_noop(call_handlers):
    assert await handle_ask_error(ExcA(), "m", call_handlers, {}) is False


async def test_tuple_key_matches_any_listed_type():
    calls = []

    async def handler(exc, m):
        calls.append(exc)

    ran = await handle_ask_error(ExcA(), "m", {(ExcB, ExcA): handler}, {})
    assert ran is True and len(calls) == 1


async def test_sync_handler_is_supported():
    calls = []

    def handler(exc, m):
        calls.append(exc)

    ran = await handle_ask_error(ExcA(), "m", {ExcA: handler}, {})
    assert ran is True and len(calls) == 1


# --- handle_ask_error(): call-vs-client precedence -------------------------


async def test_call_level_handler_wins_over_an_identical_client_key():
    calls = []
    call_handlers = {ExcA: lambda exc, m: calls.append("call")}
    client_handlers = {ExcA: lambda exc, m: calls.append("client")}

    await handle_ask_error(ExcA(), "m", call_handlers, client_handlers)

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

    await handle_ask_error(ExcA("boom"), "m", call_handlers, client_handlers)

    assert calls == ["call-specific"], (
        "client's broader handler ran instead of the call's specific one"
    )


async def test_client_handler_runs_only_when_the_call_had_no_match():
    calls = []
    call_handlers = {ExcB: lambda exc, m: calls.append("call")}
    client_handlers = {ExcA: lambda exc, m: calls.append("client")}

    await handle_ask_error(ExcA("boom"), "m", call_handlers, client_handlers)

    assert calls == ["client"]


async def test_client_handler_runs_when_the_call_passed_none():
    calls = []
    client_handlers = {ExcA: lambda exc, m: calls.append("client")}

    await handle_ask_error(ExcA("boom"), "m", None, client_handlers)

    assert calls == ["client"]


async def test_neither_mapping_matching_reports_false():
    ran = await handle_ask_error(ExcA("boom"), "m", {ExcB: lambda e, m: None}, {})
    assert ran is False


# --- the update_type lookup ask()'s except block performs ------------------


async def test_ask_error_handlers_lookup_is_scoped_to_the_calls_update_type():
    """Reproduces exactly what ask()'s except block does:
    `self.ask_error_handlers.get(update_type, {})` before calling
    handle_ask_error. A Message-registered handler must not leak into a
    CallbackQuery-flavoured ask()."""
    c = make_client()
    calls = []
    c.register_ask_error_handler(
        ExcA, lambda exc, m: calls.append("message-handler"), update_type=Message
    )

    client_handlers = c.ask_error_handlers.get(CallbackQuery, {})
    await handle_ask_error(ExcA("boom"), "m", None, client_handlers)

    assert calls == [], "Message's handler ran for a CallbackQuery-scoped ask()"


async def test_ask_error_handlers_lookup_finds_the_matching_update_type():
    c = make_client()
    calls = []
    c.register_ask_error_handler(
        ExcA, lambda exc, m: calls.append("cb-handler"), update_type=CallbackQuery
    )

    client_handlers = c.ask_error_handlers.get(CallbackQuery, {})
    await handle_ask_error(ExcA("boom"), "m", None, client_handlers)

    assert calls == ["cb-handler"]


# --- ask() itself, end to end -----------------------------------------------
#
# The tests above pin handle_ask_error() and the .get(update_type) lookup in
# isolation, but neither proves ask()'s except block actually calls them the
# way it's supposed to — a change to that one block (e.g. flattening the
# per-update_type scoping back into one shared mapping) would slip past every
# test above. These two go through Client.ask() itself, with send_message and
# the listener faked out so no network is needed.


class _RaisingListener:
    """Stands in for a registered UpdateListener whose wait raised ExcA."""

    async def __call__(self, **kw):
        raise ExcA("boom")


def _install_raising_ask(c, update_type=Message):
    c.dispatcher.listeners[update_type] = _RaisingListener()

    async def fake_send(**kw):
        return SimpleNamespace(id=5, chat=None)

    c.send_message = fake_send


async def test_ask_routes_a_listening_error_to_the_scoped_client_handler():
    c = make_client()
    calls = []
    _install_raising_ask(c, update_type=Message)

    c.register_ask_error_handler(
        ExcA, lambda exc, m: calls.append("message"), update_type=Message
    )
    c.register_ask_error_handler(
        ExcA, lambda exc, m: calls.append("callback_query"), update_type=CallbackQuery
    )

    with pytest.raises(ExcA):
        await c.ask(100, "hi")

    assert calls == ["message"], (
        "ask()'s except block did not scope its client_handlers lookup to "
        "the call's own update_type"
    )


async def test_ask_still_re_raises_after_running_the_client_handler():
    c = make_client()
    _install_raising_ask(c)
    c.register_ask_error_handler(ExcA, lambda exc, m: None)

    with pytest.raises(ExcA):
        await c.ask(100, "hi")


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
#
# ask_error_handlers is keyed by update_type: {Message: {...}, CallbackQuery:
# {...}}. register_/unregister_ each default update_type to Message, matching
# ask()'s own default.


def test_register_ask_error_handler_adds_an_entry_under_message_by_default():
    c = make_client()
    handler = lambda exc, m: None

    c.register_ask_error_handler(ExcA, handler)

    assert c.ask_error_handlers == {Message: {ExcA: handler}}


def test_register_ask_error_handler_respects_an_explicit_update_type():
    c = make_client()
    handler = lambda exc, m: None

    c.register_ask_error_handler(ExcA, handler, update_type=CallbackQuery)

    assert c.ask_error_handlers == {CallbackQuery: {ExcA: handler}}


def test_register_ask_error_handler_keeps_update_types_independent():
    """A handler registered for Message must not become visible under
    CallbackQuery, or vice versa — the two update types must not share a
    single flat mapping."""
    c = make_client()
    msg_handler = lambda exc, m: None
    cb_handler = lambda exc, m: None

    c.register_ask_error_handler(ExcA, msg_handler, update_type=Message)
    c.register_ask_error_handler(ExcA, cb_handler, update_type=CallbackQuery)

    assert c.ask_error_handlers[Message] == {ExcA: msg_handler}
    assert c.ask_error_handlers[CallbackQuery] == {ExcA: cb_handler}


def test_register_ask_error_handler_replaces_an_existing_entry():
    """No ValueError on re-registering — unlike register_listener() and
    friends, this has no dispatcher lifecycle or duplicate check."""
    c = make_client()
    first = lambda exc, m: None
    second = lambda exc, m: None

    c.register_ask_error_handler(ExcA, first)
    c.register_ask_error_handler(ExcA, second)

    assert c.ask_error_handlers == {Message: {ExcA: second}}


def test_register_ask_error_handler_accepts_a_tuple_key():
    c = make_client()
    handler = lambda exc, m: None

    c.register_ask_error_handler((ExcA, ExcB), handler)

    assert c.ask_error_handlers == {Message: {(ExcA, ExcB): handler}}


def test_unregister_ask_error_handler_removes_an_entry_and_reports_true():
    c = make_client()
    c.register_ask_error_handler(ExcA, lambda exc, m: None)

    removed = c.unregister_ask_error_handler(ExcA)

    assert removed is True
    assert c.ask_error_handlers == {Message: {}}


def test_unregister_ask_error_handler_reports_false_when_nothing_registered():
    c = make_client()
    assert c.unregister_ask_error_handler(ExcA) is False


def test_unregister_ask_error_handler_reports_false_for_an_unregistered_update_type():
    """Nothing was ever registered for CallbackQuery, so the lookup must not
    raise (e.g. via a bare `self.ask_error_handlers[update_type]`)."""
    c = make_client()
    assert c.unregister_ask_error_handler(ExcA, update_type=CallbackQuery) is False


def test_unregister_ask_error_handler_requires_the_exact_key():
    """A tuple key is not decomposed: registering (ExcA, ExcB) and then
    unregistering plain ExcA must not remove it."""
    c = make_client()
    c.register_ask_error_handler((ExcA, ExcB), lambda exc, m: None)

    removed = c.unregister_ask_error_handler(ExcA)

    assert removed is False
    assert len(c.ask_error_handlers[Message]) == 1


def test_unregister_ask_error_handler_requires_the_exact_update_type():
    """Registered under Message; unregistering the same exc_types under
    CallbackQuery must not touch it."""
    c = make_client()
    c.register_ask_error_handler(ExcA, lambda exc, m: None, update_type=Message)

    removed = c.unregister_ask_error_handler(ExcA, update_type=CallbackQuery)

    assert removed is False
    assert c.ask_error_handlers[Message] != {}
