"""Tests for the Redis coordinator backend, against `fakeredis`.

The lock is redis-py's distributed lock and the handled registry is one
expiring key per update, so these tests check both the Redis state the
backend writes and the behaviour callers see.
"""

from __future__ import annotations as _annotations

import asyncio
from typing import Any, TYPE_CHECKING

import pytest

fakeredis = pytest.importorskip("fakeredis")
pytest.importorskip("lupa")  # fakeredis needs lupa to run Lua scripts

from fakeredis import aioredis as fake_aioredis  # noqa: E402
from pyrogram.types import CallbackQuery, Message  # noqa: E402
from redis.asyncio.lock import Lock  # noqa: E402
from redis.exceptions import LockError  # noqa: E402

from pyroflow.update_coordinator import redis_update_coordinator  # noqa: E402
from pyroflow.update_coordinator.redis_update_coordinator import (  # noqa: E402
    RedisUpdateCoordinator,
)

if TYPE_CHECKING:
    from collections.abc import AsyncIterator


@pytest.fixture
async def redis() -> AsyncIterator[fake_aioredis.FakeRedis]:
    server = fake_aioredis.FakeRedis()
    try:
        yield server
    finally:
        await server.aclose()


def _coord(redis: fake_aioredis.FakeRedis, **kw: Any) -> RedisUpdateCoordinator:
    kw.setdefault("sleep", 0.01)
    kw.setdefault("blocking_timeout", 0.05)
    return RedisUpdateCoordinator(redis, Message, **kw)


# --- construction ----------------------------------------------------------


def test_init_stores_the_client_and_default_sleep(redis: fake_aioredis.FakeRedis) -> None:
    coord = RedisUpdateCoordinator(redis, Message)

    assert coord.redis is redis
    assert coord.sleep == 0.1


# --- build_key --------------------------------------------------------------


def test_build_key_renders_each_section_exactly(redis: fake_aioredis.FakeRedis) -> None:
    coord = RedisUpdateCoordinator(redis, Message)

    assert coord.build_key((-100123, 42), "lock") == "update|lock|Message|-100123|42"
    assert coord.build_key((-100123, 42), "handled") == "update|handled|Message|-100123|42"


def test_build_key_uses_the_update_type_name(redis: fake_aioredis.FakeRedis) -> None:
    assert (
        RedisUpdateCoordinator(redis, CallbackQuery).build_key((1,))
        == "update|lock|CallbackQuery|1"
    )


def test_build_key_stringifies_str_components(redis: fake_aioredis.FakeRedis) -> None:
    assert (
        RedisUpdateCoordinator(redis, Message).build_key(("abc", 1)) == "update|lock|Message|abc|1"
    )


def test_build_key_of_an_empty_tuple(redis: fake_aioredis.FakeRedis) -> None:
    assert RedisUpdateCoordinator(redis, Message).build_key(()) == "update|lock|Message|"


def test_build_key_rejects_an_unknown_section(redis: fake_aioredis.FakeRedis) -> None:
    with pytest.raises(KeyError):
        RedisUpdateCoordinator(redis, Message).build_key((1,), "other")  # type: ignore[arg-type]


# --- the lock ---------------------------------------------------------------


def test_lock_is_configured_from_the_coordinator(redis: fake_aioredis.FakeRedis) -> None:
    coord = _coord(redis, lock_ttl=30)
    lock = coord.lock((1, 2))

    assert isinstance(lock, Lock)
    assert lock.name == coord.build_key((1, 2), "lock")
    assert lock.timeout == 30
    assert lock.sleep == 0.01
    assert lock.blocking_timeout == 0.05
    assert lock.thread_local is False


async def test_lock_is_acquirable_and_expires_after_lock_ttl(
    redis: fake_aioredis.FakeRedis,
) -> None:
    coord = _coord(redis, lock_ttl=30)
    lock = coord.lock((1, 2))

    assert await lock.acquire() is True
    assert 0 < await redis.pttl(lock.name) <= 30_000


async def test_lock_is_exclusive_across_instances(redis: fake_aioredis.FakeRedis) -> None:
    coord = _coord(redis)
    held = coord.lock((1, 2))
    await held.acquire()

    # A second session (another coordinator on the same Redis) gives up.
    assert await _coord(redis).lock((1, 2)).acquire() is False

    await held.release()
    assert await coord.lock((1, 2)).acquire() is True


async def test_lock_scopes_are_independent(redis: fake_aioredis.FakeRedis) -> None:
    coord = _coord(redis)

    assert await coord.lock((1, 2)).acquire() is True
    assert await coord.lock((3, 4)).acquire() is True


async def test_lock_of_a_dead_holder_expires(redis: fake_aioredis.FakeRedis) -> None:
    coord = _coord(redis, lock_ttl=0.05)
    await coord.lock((1, 2)).acquire()  # never released

    await asyncio.sleep(0.08)
    assert await coord.lock((1, 2)).acquire() is True


async def test_async_with_raises_on_a_held_lock(redis: fake_aioredis.FakeRedis) -> None:
    coord = _coord(redis)
    await coord.lock((1, 2)).acquire()

    with pytest.raises(LockError):
        async with coord.lock((1, 2)):
            pytest.fail("entered the critical section without the lock")


async def test_lock_can_be_released_from_another_task(
    redis: fake_aioredis.FakeRedis,
) -> None:
    # `thread_local=False`: the token survives a hop to another task.
    lock = _coord(redis).lock((1, 2))
    await lock.acquire()

    await asyncio.create_task(lock.release())
    assert await redis.exists(lock.name) == 0


# --- the handled registry -----------------------------------------------------


async def test_mark_handled_then_is_handled(redis: fake_aioredis.FakeRedis) -> None:
    coord = _coord(redis)
    await coord.mark_handled((1, 2))

    result = await coord.is_handled((1, 2))
    assert result is True
    assert await coord.is_handled((1, 3)) is False


async def test_mark_handled_writes_an_expiring_handled_key(
    redis: fake_aioredis.FakeRedis,
) -> None:
    coord = _coord(redis, handled_ttl=20)
    await coord.mark_handled((1, 2))

    key = coord.build_key((1, 2), "handled")
    assert await redis.get(key) == b"1"
    assert 0 < await redis.pttl(key) <= 20_000
    assert await redis.exists(coord.build_key((1, 2), "lock")) == 0


async def test_mark_handled_keeps_a_sub_second_ttl(redis: fake_aioredis.FakeRedis) -> None:
    coord = _coord(redis, handled_ttl=0.5)
    await coord.mark_handled((1, 2))

    assert 0 < await redis.pttl(coord.build_key((1, 2), "handled")) <= 500


async def test_mark_handled_again_refreshes_the_expiry(redis: fake_aioredis.FakeRedis) -> None:
    coord = _coord(redis, handled_ttl=20)
    key = coord.build_key((1, 2), "handled")
    await coord.mark_handled((1, 2))
    await redis.pexpire(key, 100)

    await coord.mark_handled((1, 2))
    assert await redis.pttl(key) > 100


async def test_handled_entries_expire(redis: fake_aioredis.FakeRedis) -> None:
    coord = _coord(redis, handled_ttl=0.05)
    await coord.mark_handled((1, 2))

    await asyncio.sleep(0.08)
    assert await coord.is_handled((1, 2)) is False


# --- the two primitives must not collide ------------------------------------


async def test_holding_a_lock_does_not_mark_it_handled(redis: fake_aioredis.FakeRedis) -> None:
    coord = _coord(redis)
    await coord.lock((1, 2)).acquire()

    assert await coord.is_handled((1, 2)) is False


async def test_marking_handled_does_not_lock(redis: fake_aioredis.FakeRedis) -> None:
    coord = _coord(redis)
    await coord.mark_handled((1, 2))

    assert await coord.lock((1, 2)).acquire() is True


# --- lifecycle and exports ----------------------------------------------------


async def test_start_and_stop_leave_redis_untouched(redis: fake_aioredis.FakeRedis) -> None:
    coord = _coord(redis)
    await coord.mark_handled((1, 2))

    assert await coord.start() is None
    assert await coord.stop() is None
    assert await coord.is_handled((1, 2)) is True


def test_all_exports_only_the_coordinator() -> None:
    assert redis_update_coordinator.__all__ == ("RedisUpdateCoordinator",)
