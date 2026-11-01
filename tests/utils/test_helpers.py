"""Tests for ``UpdateBound`` enforcement and ``handle_ask_error()``.

handle_ask_error() is the exact function ask()'s except block calls, so
matching and precedence are tested by calling it directly rather than by
reimplementing its routing logic in the test.
"""

from __future__ import annotations as _annotations

import asyncio
import inspect
import threading
from abc import ABC
from typing import Any

import pytest

from pyroflow.utils import AsyncioLock, UpdateBound, handle_ask_error, helpers
from pyrogram.types import Message


class ExcA(Exception):
    pass


class ExcB(Exception):
    pass


# --- UpdateBound ----------------------------------------------------------


def test_update_bound_accepts_valid_pyrogram_update_type() -> None:
    class Good(UpdateBound):
        __update_type__ = Message

    assert Good.__update_type__ is Message


def test_update_bound_requires_update_type() -> None:
    with pytest.raises(TypeError):

        class Missing(UpdateBound):  # pragma: no cover - class body raises
            pass


def test_update_bound_rejects_non_update_type() -> None:
    with pytest.raises(TypeError):

        class BadType(UpdateBound):  # pragma: no cover - class body raises
            __update_type__ = int


def test_update_bound_abstract_subclass_is_exempt() -> None:
    # An ABC subclass is allowed to omit __update_type__ (it is abstract).
    class StillAbstract(ABC, UpdateBound):
        pass

    assert not hasattr(StillAbstract, "__update_type__")


def test_validate_update_type_check() -> None:
    class Good(UpdateBound):
        __update_type__ = Message

    Good.validate_update(Message(id=1))  # no raise
    with pytest.raises(TypeError):
        Good.validate_update(object())


# --- handle_ask_error(): matching -------------------------------------------


async def test_matching_handler_runs_and_reports_true() -> None:
    calls = []

    async def handler(exc: Exception, m: object) -> None:
        calls.append((exc, m))

    ran = await handle_ask_error(ExcA(), "the message", {ExcA: handler}, {})
    assert ran is True
    assert len(calls) == 1 and calls[0][1] == "the message"


async def test_non_matching_handler_does_not_run() -> None:
    calls = []

    async def handler(exc: Exception, m: object) -> None:
        calls.append(exc)

    ran = await handle_ask_error(ExcA(), "m", {ExcB: handler}, {})
    assert ran is False
    assert calls == []


@pytest.mark.parametrize("call_handlers", [{}, None])
async def test_empty_or_missing_mapping_is_a_noop(call_handlers: dict[Any, Any] | None) -> None:
    assert await handle_ask_error(ExcA(), "m", call_handlers, {}) is False


async def test_tuple_key_matches_any_listed_type() -> None:
    calls = []

    async def handler(exc: Exception, m: object) -> None:
        calls.append(exc)

    ran = await handle_ask_error(ExcA(), "m", {(ExcB, ExcA): handler}, {})
    assert ran is True and len(calls) == 1


async def test_sync_handler_is_supported() -> None:
    calls = []

    def handler(exc: Exception, m: object) -> None:
        calls.append(exc)

    ran = await handle_ask_error(ExcA(), "m", {ExcA: handler}, {})
    assert ran is True and len(calls) == 1


# --- handle_ask_error(): call-vs-client precedence -------------------------


async def test_call_level_handler_wins_over_an_identical_client_key() -> None:
    calls = []
    call_handlers = {ExcA: lambda exc, m: calls.append("call")}
    client_handlers = {ExcA: lambda exc, m: calls.append("client")}

    await handle_ask_error(ExcA(), "m", call_handlers, client_handlers)

    assert calls == ["call"]


async def test_call_level_handler_wins_over_a_broader_client_handler() -> None:
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


async def test_client_handler_runs_only_when_the_call_had_no_match() -> None:
    calls = []
    call_handlers = {ExcB: lambda exc, m: calls.append("call")}
    client_handlers = {ExcA: lambda exc, m: calls.append("client")}

    await handle_ask_error(ExcA("boom"), "m", call_handlers, client_handlers)

    assert calls == ["client"]


async def test_client_handler_runs_when_the_call_passed_none() -> None:
    calls = []
    client_handlers = {ExcA: lambda exc, m: calls.append("client")}

    await handle_ask_error(ExcA("boom"), "m", None, client_handlers)

    assert calls == ["client"]


async def test_neither_mapping_matching_reports_false() -> None:
    ran = await handle_ask_error(ExcA("boom"), "m", {ExcB: lambda e, m: None}, {})
    assert ran is False


async def test_handler_exception_is_swallowed() -> None:
    def handler(exc: Exception, m: object) -> None:
        raise RuntimeError

    assert await handle_ask_error(ExcA(), "m", {ExcA: handler}) is True


async def test_handler_receives_the_exception_and_message() -> None:
    exc = ExcA()
    seen: list[tuple[Exception, object]] = []

    async def handler(e: Exception, m: object) -> None:
        seen.append((e, m))

    await handle_ask_error(exc, "msg", {ExcA: handler})

    assert seen == [(exc, "msg")]


async def test_first_matching_key_in_insertion_order_wins() -> None:
    calls: list[str] = []
    mapping = {
        Exception: lambda exc, m: calls.append("broad"),
        ExcA: lambda exc, m: calls.append("specific"),
    }

    await handle_ask_error(ExcA(), "m", mapping)

    assert calls == ["broad"]


async def test_sync_handler_runs_in_a_worker_thread() -> None:
    threads: list[threading.Thread] = []

    def handler(exc: Exception, m: object) -> None:
        threads.append(threading.current_thread())

    await handle_ask_error(ExcA(), "m", {ExcA: handler})

    assert threads and threads[0] is not threading.current_thread()


async def test_no_mappings_reports_false() -> None:
    assert await handle_ask_error(ExcA(), "m") is False


# --- AsyncioLock ----------------------------------------------------------


def test_asyncio_lock_is_an_asyncio_lock_with_async_release() -> None:
    assert issubclass(AsyncioLock, asyncio.Lock)
    assert inspect.iscoroutinefunction(AsyncioLock.release)
    assert inspect.iscoroutinefunction(AsyncioLock.__aexit__)


async def test_asyncio_lock_release_unlocks() -> None:
    lock = AsyncioLock()
    await lock.acquire()
    assert lock.locked()

    assert await lock.release() is None
    assert not lock.locked()


async def test_asyncio_lock_release_when_unlocked_raises() -> None:
    with pytest.raises(RuntimeError):
        await AsyncioLock().release()


async def test_asyncio_lock_context_manager_holds_then_releases() -> None:
    lock = AsyncioLock()

    async with lock:
        assert lock.locked()

    assert not lock.locked()


async def test_asyncio_lock_aexit_releases_on_exception() -> None:
    lock = AsyncioLock()

    with pytest.raises(ExcA):
        async with lock:
            raise ExcA

    assert not lock.locked()


async def test_asyncio_lock_aexit_releases_directly() -> None:
    lock = AsyncioLock()
    await lock.acquire()

    assert await lock.__aexit__(None, None, None) is None
    assert not lock.locked()


# --- UpdateBound: more branches ------------------------------------------


def test_update_bound_missing_type_message() -> None:
    with pytest.raises(TypeError, match="Missing must define __update_type__"):

        class Missing(UpdateBound):  # pragma: no cover - class body raises
            pass


def test_update_bound_rejects_an_update_instance() -> None:
    with pytest.raises(TypeError, match=r"__update_type__ must be a subclass of Update"):

        class Instance(UpdateBound):  # pragma: no cover - class body raises
            __update_type__ = Message(id=1)


def test_update_bound_abc_exemption_needs_abc_as_a_direct_base() -> None:
    class Abstract(ABC, UpdateBound):
        pass

    with pytest.raises(TypeError, match="must define __update_type__"):

        class Concrete(Abstract):  # pragma: no cover - class body raises
            pass


def test_update_bound_subclass_inherits_update_type() -> None:
    class Good(UpdateBound):
        __update_type__ = Message

    class Child(Good):
        pass

    assert Child.__update_type__ is Message


def test_update_bound_init_subclass_forwards_kwargs() -> None:
    seen: dict[str, Any] = {}

    class Recorder:
        def __init_subclass__(cls, **kw: Any) -> None:
            seen.update(kw)
            super().__init_subclass__()

    class Good(UpdateBound, Recorder, flag=True):
        __update_type__ = Message

    assert seen == {"flag": True}


def test_update_bound_init_passes_kwargs_to_the_next_base() -> None:
    class Store:
        def __init__(self, **kw: Any) -> None:
            self.kw = kw

    class Good(UpdateBound, Store):
        __update_type__ = Message

    assert Good(a=1).kw == {"a": 1}


def test_update_bound_init_rejects_an_abstract_subclass_without_type() -> None:
    class Abstract(ABC, UpdateBound):
        pass

    with pytest.raises(TypeError, match="Abstract must define __update_type__"):
        Abstract()


def test_update_bound_init_rejects_a_type_replaced_after_definition() -> None:
    class Good(UpdateBound):
        __update_type__ = Message

    Good.__update_type__ = int  # type: ignore[assignment]

    with pytest.raises(TypeError, match=r"Good.__update_type__ must be a subclass of Update"):
        Good()


def test_validate_update_accepts_a_subclass_instance() -> None:
    class SubMessage(Message):
        pass

    class Good(UpdateBound):
        __update_type__ = Message

    Good.validate_update(SubMessage(id=1))


def test_validate_update_error_message() -> None:
    class Good(UpdateBound):
        __update_type__ = Message

    with pytest.raises(TypeError, match="Expected Message, got str"):
        Good.validate_update("text")


def test_module_all_lists_public_names() -> None:
    assert helpers.__all__ == ("AsyncioLock", "UpdateBound", "handle_ask_error")
    assert all(hasattr(helpers, name) for name in helpers.__all__)
