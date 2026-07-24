"""Unit tests for the async/iter/validate utility layer."""

import asyncio
import functools

import pytest

from pyroflow.utils import (
    flat_cont,
    gather_helper,
    is_container,
    is_exception,
    iscoroutinefunction_wrapped,
    maybe_awaitable,
    safe_await,
    to_thread,
)


# --- iter_tools / validate_tools -----------------------------------------


def test_flat_cont_flattens_nested_and_drops_none():
    assert flat_cont([1, [2, [3, None]], None], (4,)) == [1, 2, 3, 4]


def test_flat_cont_treats_str_and_bytes_as_atomic():
    assert flat_cont(["ab", ["cd"]]) == ["ab", "cd"]
    assert flat_cont([b"xy"]) == [b"xy"]


def test_is_container_excludes_str_bytes():
    assert is_container([1, 2])
    assert is_container((1, 2))
    assert not is_container("abc")
    assert not is_container(b"abc")
    assert not is_container(5)


def test_is_exception():
    assert is_exception(ValueError())
    assert is_exception(KeyboardInterrupt())  # BaseException too
    assert not is_exception("not an exception")


def test_iscoroutinefunction_wrapped():
    async def coro():
        return 1

    def sync():
        return 1

    assert iscoroutinefunction_wrapped(coro)
    assert not iscoroutinefunction_wrapped(sync)
    # sees through functools.partial / wraps
    assert iscoroutinefunction_wrapped(functools.partial(coro))

    @functools.wraps(coro)
    def wrapper(*a, **k):  # pragma: no cover - not called
        return coro(*a, **k)

    assert iscoroutinefunction_wrapped(wrapper)


# --- async_tools ----------------------------------------------------------


async def test_maybe_awaitable_with_sync_callable():
    def add(x, y):
        return x + y

    assert await maybe_awaitable(add, 2, 3) == 5


async def test_maybe_awaitable_with_async_callable():
    async def add(x, y):
        return x + y

    assert await maybe_awaitable(add, 2, 3) == 5


async def test_maybe_awaitable_with_ready_awaitable():
    async def five():
        return 5

    assert await maybe_awaitable(five()) == 5


async def test_maybe_awaitable_rejects_args_on_ready_awaitable():
    async def five():
        return 5

    coro = five()
    with pytest.raises(TypeError):
        await maybe_awaitable(coro, 1)
    coro.close()  # avoid "never awaited" warning


async def test_to_thread_runs_and_returns():
    def blocking(x):
        return x * 2

    assert await to_thread(blocking, 21) == 42


async def test_to_thread_return_exc():
    def boom():
        raise ValueError("nope")

    result = await to_thread(boom, return_exc=True, log_exc=False)
    assert isinstance(result, ValueError)


async def test_gather_helper_returns_in_order_with_exceptions():
    async def ok(v):
        return v

    async def boom():
        raise ValueError("x")

    results = await gather_helper(
        (ok(1), boom(), ok(3)), return_exc=True, log_exc=False
    )
    assert results[0] == 1
    assert isinstance(results[1], ValueError)
    assert results[2] == 3


async def test_gather_helper_flattens_nested_awaitables():
    async def ok(v):
        return v

    results = await gather_helper((ok(1), ok(2)), (ok(3),), log_exc=False)
    assert set(results) == {1, 2, 3}


async def test_safe_await_single_returns_value():
    async def ok():
        return 99

    assert await safe_await(ok(), log_exc=False) == 99


async def test_safe_await_reraises_when_not_return_exc():
    async def boom():
        raise KeyError("k")

    with pytest.raises(KeyError):
        await safe_await(boom(), return_exc=False, log_exc=False)
