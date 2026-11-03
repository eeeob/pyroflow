"""Tests for ``UpdateBound`` enforcement and ``handle_ask_error()``.

handle_ask_error() is the exact function ask()'s except block calls, so
matching and precedence are tested by calling it directly rather than by
reimplementing its routing logic in the test.
"""

from __future__ import annotations as _annotations

import threading
from abc import ABC
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
from typing import Any

import pytest

from pyroflow.utils import (
    AsyncioLock,
    UpdateBound,
    get_update_executor,
    handle_ask_error,
    helpers,
    redis_token_lock,
)
from pyrogram.types import Message


class ExcA(Exception):
    pass


class ExcB(Exception):
    pass


# --- UpdateBound ----------------------------------------------------------


def test_update_bound_rejects_non_update_type() -> None:
    with pytest.raises(TypeError):

        class BadType(UpdateBound):  # pragma: no cover - class body raises
            __update_type__ = int


# --- handle_ask_error(): matching -------------------------------------------


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


# --- handle_ask_error(): call-vs-client precedence -------------------------


async def test_call_level_handler_wins_over_an_identical_client_key() -> None:
    calls = []
    call_handlers = {ExcA: lambda exc, m: calls.append("call")}
    client_handlers = {ExcA: lambda exc, m: calls.append("client")}

    await handle_ask_error(ExcA(), "m", call_handlers, client_handlers)

    assert calls == ["call"]


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


async def test_asyncio_lock_release_unlocks() -> None:
    lock = AsyncioLock()
    await lock.acquire()
    assert lock.locked()

    assert await lock.release() is None
    assert not lock.locked()


async def test_asyncio_lock_aexit_releases_on_exception() -> None:
    lock = AsyncioLock()

    with pytest.raises(ExcA):
        async with lock:
            raise ExcA

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


# --- get_update_executor ----------------------------------------------------


def test_get_update_executor_returns_the_client_executor() -> None:
    executor = ThreadPoolExecutor(max_workers=1)
    try:
        update = SimpleNamespace(_client=SimpleNamespace(executor=executor))
        assert get_update_executor(update) is executor
    finally:
        executor.shutdown()


def test_get_update_executor_without_client() -> None:
    assert get_update_executor(SimpleNamespace()) is None


def test_get_update_executor_client_without_executor() -> None:
    assert get_update_executor(SimpleNamespace(_client=SimpleNamespace())) is None


async def test_redis_token_lock_writes_its_token_and_releases() -> None:
    fake_aioredis = pytest.importorskip("fakeredis.aioredis")
    pytest.importorskip("lupa")  # release runs a Lua script
    lock_module = pytest.importorskip("redis.asyncio.lock")

    redis = fake_aioredis.FakeRedis()
    try:
        lock = redis_token_lock(redis, "k", token="owner:1", timeout=5)

        assert isinstance(lock, lock_module.Lock)
        assert lock.token == "owner:1"
        assert await lock.acquire() is True
        assert await redis.get("k") == b"owner:1"
        await lock.release()
        assert await redis.exists("k") == 0
    finally:
        await redis.aclose()


async def test_redis_token_lock_async_with_writes_its_token() -> None:
    fake_aioredis = pytest.importorskip("fakeredis.aioredis")
    pytest.importorskip("lupa")
    redis = fake_aioredis.FakeRedis()
    try:
        async with redis_token_lock(redis, "k", token="owner:1"):
            assert await redis.get("k") == b"owner:1"
    finally:
        await redis.aclose()


async def test_redis_token_lock_explicit_acquire_token_wins() -> None:
    fake_aioredis = pytest.importorskip("fakeredis.aioredis")
    redis = fake_aioredis.FakeRedis()
    try:
        assert await redis_token_lock(redis, "k", token="owner:1").acquire(token="other") is True
        assert await redis.get("k") == b"other"
    finally:
        await redis.aclose()


async def test_redis_token_lock_returns_false_when_held() -> None:
    fake_aioredis = pytest.importorskip("fakeredis.aioredis")
    redis = fake_aioredis.FakeRedis()
    try:
        await redis.set("k", "someone")
        lock = redis_token_lock(redis, "k", token="owner:1", blocking_timeout=0.05, sleep=0.01)

        assert await lock.acquire() is False
        assert await redis.get("k") == b"someone"
    finally:
        await redis.aclose()


def test_redis_token_lock_class_is_built_once() -> None:
    lock_module = pytest.importorskip("redis.asyncio.lock")

    cls = helpers._redis_token_lock_class()

    assert cls is helpers._redis_token_lock_class()
    assert isinstance(cls, type)
    assert issubclass(cls, lock_module.Lock)


def test_module_all_lists_public_names() -> None:
    assert helpers.__all__ == (
        "AsyncioLock",
        "UpdateBound",
        "get_update_executor",
        "handle_ask_error",
        "redis_token_lock",
    )
