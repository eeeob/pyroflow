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
from pytrove.enums import TimeUnit  # noqa: E402
from redis.asyncio.lock import Lock  # noqa: E402
from redis.exceptions import LockError  # noqa: E402

from pyroflow.errors import UpdateAlreadyHandled  # noqa: E402
from pyroflow.models import ListenerKey  # noqa: E402
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


def test_init_stores_the_client_and_defaults(redis: fake_aioredis.FakeRedis) -> None:
    coord = RedisUpdateCoordinator(redis, Message)

    assert coord.redis is redis
    assert coord.lock_ttl == TimeUnit.HOUR == 3600
    assert coord.listener_ttl == 60
    assert coord.sleep == 0.1


def test_init_gives_each_coordinator_its_own_fingerprint(redis: fake_aioredis.FakeRedis) -> None:
    first, second = _coord(redis), _coord(redis)

    assert len(first.fingerprint) == 32
    int(first.fingerprint, 16)
    assert first.fingerprint != second.fingerprint


# --- build_key --------------------------------------------------------------


def test_build_key_renders_each_section_exactly(redis: fake_aioredis.FakeRedis) -> None:
    coord = RedisUpdateCoordinator(redis, Message)

    assert coord.build_key((-100123, 42), "lock") == "update|lock|Message|-100123|42"
    assert coord.build_key((-100123, 42), "handled") == "update|handled|Message|-100123|42"
    assert coord.build_key((-100123, 42), "listen") == "update|listen|Message|-100123|42"


def test_listener_key_marks_missing_components(redis: fake_aioredis.FakeRedis) -> None:
    coord = RedisUpdateCoordinator(redis, Message)

    assert coord._listener_key(ListenerKey(1, None, 3)) == "update|listen|Message|1|_|3"
    assert coord._listener_key(ListenerKey(1)) == "update|listen|Message|1|_|_"


def test_decode_turns_bytes_into_text() -> None:
    assert redis_update_coordinator._decode(b"a") == "a"
    assert redis_update_coordinator._decode("b") == "b"
    assert redis_update_coordinator._decode(None) is None


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


async def test_mark_handled_twice_raises_and_keeps_the_expiry(
    redis: fake_aioredis.FakeRedis,
) -> None:
    coord = _coord(redis, handled_ttl=20)
    key = coord.build_key((1, 2), "handled")
    await coord.mark_handled((1, 2))
    await redis.pexpire(key, 5000)

    with pytest.raises(UpdateAlreadyHandled) as excinfo:
        await _coord(redis).mark_handled((1, 2))

    assert excinfo.value.value == (1, 2)
    assert 0 < await redis.pttl(key) <= 5000


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


async def test_lock_value_starts_with_the_fingerprint(redis: fake_aioredis.FakeRedis) -> None:
    coord = _coord(redis)

    assert await coord.lock((1,)).acquire() is True

    value = (await redis.get(coord.build_key((1,)))).decode()
    assert value.startswith(f"{coord.fingerprint}:")
    assert len(value) > len(coord.fingerprint) + 1


async def test_async_with_also_stamps_the_fingerprint(redis: fake_aioredis.FakeRedis) -> None:
    coord = _coord(redis)

    async with coord.lock((1,)):
        value = (await redis.get(coord.build_key((1,)))).decode()

    assert value.startswith(f"{coord.fingerprint}:")


async def test_each_lock_gets_its_own_value(redis: fake_aioredis.FakeRedis) -> None:
    coord = _coord(redis)
    await coord.lock((1,)).acquire()
    await coord.lock((2,)).acquire()

    assert await redis.get(coord.build_key((1,))) != await redis.get(coord.build_key((2,)))


async def test_an_expired_lock_does_not_release_a_newer_one_of_its_coordinator(
    redis: fake_aioredis.FakeRedis,
) -> None:
    coord = _coord(redis, lock_ttl=0.05)
    stale = coord.lock((1,))
    await stale.acquire()
    await asyncio.sleep(0.1)
    await coord.lock((1,)).acquire()

    with pytest.raises(LockError):
        await stale.release()

    assert await redis.exists(coord.build_key((1,))) == 1


async def test_start_keeps_a_fingerprint_no_lock_carries(redis: fake_aioredis.FakeRedis) -> None:
    other = _coord(redis)
    await other.lock((1,)).acquire()
    coord = _coord(redis)
    fingerprint = coord.fingerprint

    await coord.start()

    assert coord.fingerprint == fingerprint


@pytest.mark.parametrize("decode_responses", [False, True])
async def test_start_replaces_a_fingerprint_a_lock_already_carries(
    decode_responses: bool,  # noqa: FBT001  # pytest passes parameters positionally
) -> None:
    redis = fake_aioredis.FakeRedis(decode_responses=decode_responses)
    try:
        coord = _coord(redis)
        taken = coord.fingerprint
        await redis.set(coord.build_key((1,)), f"{taken}:other-session")

        await coord.start()

        assert coord.fingerprint != taken
        assert len(coord.fingerprint) == 32
    finally:
        await redis.aclose()


async def test_stop_deletes_only_the_locks_this_coordinator_holds(
    redis: fake_aioredis.FakeRedis,
) -> None:
    coord, other = _coord(redis), _coord(redis)
    await coord.lock((1,)).acquire()
    await coord.lock((2,)).acquire()
    await other.lock((3,)).acquire()
    await coord.mark_handled((1,))

    await coord.stop()

    assert await redis.exists(coord.build_key((1,)), coord.build_key((2,))) == 0
    assert await redis.exists(other.build_key((3,))) == 1
    assert await coord.is_handled((1,)) is True


async def test_stop_leaves_other_update_types_alone(redis: fake_aioredis.FakeRedis) -> None:
    coord = _coord(redis)
    query_coord = RedisUpdateCoordinator(redis, CallbackQuery, blocking_timeout=0.05)
    query_coord.fingerprint = coord.fingerprint
    await query_coord.lock((1,)).acquire()

    await coord.stop()

    assert await redis.exists(query_coord.build_key((1,))) == 1


async def test_start_and_stop_with_no_locks_keep_handled_keys(
    redis: fake_aioredis.FakeRedis,
) -> None:
    coord = _coord(redis)
    await coord.mark_handled((1, 2))

    assert await coord.start() is None
    assert await coord.stop() is None
    assert await coord.is_handled((1, 2)) is True


def test_script_registers_each_source_once(redis: fake_aioredis.FakeRedis) -> None:
    coord = _coord(redis)
    script = coord._script(coord.LUA_GETDEL_SCRIPT)

    assert coord._script(coord.LUA_GETDEL_SCRIPT) is script
    assert coord._script(coord.LUA_REFRESH_LISTENERS_SCRIPT) is not script


async def test_fingerprinted_keys_are_the_locks_and_registrations_of_this_type(
    redis: fake_aioredis.FakeRedis,
) -> None:
    coord = _coord(redis)
    await coord.lock((1,)).acquire()
    await coord.register_listener(ListenerKey(2), "a", replace=False)
    await coord.mark_handled((3,))
    await RedisUpdateCoordinator(redis, CallbackQuery).register_listener(
        ListenerKey(4), "b", replace=False
    )

    keys = sorted(k.decode() for k in await coord._fingerprinted_keys())

    assert keys == ["update|listen|Message|2|_|_", "update|lock|Message|1"]


# --- the listener registry ------------------------------------------------


async def test_register_listener_writes_an_expiring_owner(redis: fake_aioredis.FakeRedis) -> None:
    coord = _coord(redis, listener_ttl=30)
    key = ListenerKey(1, 2)

    assert await coord.register_listener(key, "a", replace=False) is None

    redis_key = coord._listener_key(key)
    assert await redis.get(redis_key) == b"a"
    assert 0 < await redis.pttl(redis_key) <= 30_000
    assert coord._owned_listeners == {redis_key: (key, "a")}


async def test_register_listener_without_replace_keeps_a_peer(
    redis: fake_aioredis.FakeRedis,
) -> None:
    coord, peer = _coord(redis), _coord(redis)
    await peer.register_listener(ListenerKey(1), "peer", replace=False)

    assert await coord.register_listener(ListenerKey(1), "a", replace=False) == "peer"
    assert await redis.get(coord._listener_key(ListenerKey(1))) == b"peer"
    assert coord._owned_listeners == {}


async def test_register_listener_with_replace_takes_over(redis: fake_aioredis.FakeRedis) -> None:
    coord, peer = _coord(redis), _coord(redis)
    await peer.register_listener(ListenerKey(1), "peer", replace=False)

    assert await coord.register_listener(ListenerKey(1), "a", replace=True) == "peer"
    assert await redis.get(coord._listener_key(ListenerKey(1))) == b"a"


async def test_listener_owners_reads_every_key_in_order(redis: fake_aioredis.FakeRedis) -> None:
    coord = _coord(redis)
    await coord.register_listener(ListenerKey(1, 2), "a", replace=False)

    assert await coord.listener_owners([ListenerKey(1, 2), ListenerKey(1)]) == ["a", None]
    assert await coord.listener_owners([]) == []


async def test_unregister_listener_compares_the_owner(redis: fake_aioredis.FakeRedis) -> None:
    coord = _coord(redis)
    await coord.register_listener(ListenerKey(1), "a", replace=False)

    assert await coord.unregister_listener(ListenerKey(1), "b") is False
    assert coord._owned_listeners != {}
    assert await coord.unregister_listener(ListenerKey(1), "a") is True
    assert await coord.unregister_listener(ListenerKey(1), "a") is False
    assert coord._owned_listeners == {}
    assert await redis.exists(coord._listener_key(ListenerKey(1))) == 0


async def test_cancel_listener_removes_any_owner(redis: fake_aioredis.FakeRedis) -> None:
    coord, peer = _coord(redis), _coord(redis)
    await peer.register_listener(ListenerKey(1), "peer", replace=False)

    assert await coord.cancel_listener(ListenerKey(1)) == "peer"
    assert await coord.cancel_listener(ListenerKey(1)) is None


async def test_a_registration_expires_without_renewal(redis: fake_aioredis.FakeRedis) -> None:
    coord = _coord(redis, listener_ttl=0.05)
    await coord.register_listener(ListenerKey(1), "a", replace=False)

    await asyncio.sleep(0.1)

    assert await coord.listener_owners([ListenerKey(1)]) == [None]


async def test_refresh_listeners_renews_owned_registrations(
    redis: fake_aioredis.FakeRedis,
) -> None:
    coord = _coord(redis, listener_ttl=30)
    await coord.register_listener(ListenerKey(1), "a", replace=False)
    redis_key = coord._listener_key(ListenerKey(1))
    await redis.pexpire(redis_key, 100)

    await coord.refresh_listeners()

    assert await redis.pttl(redis_key) > 100


async def test_refresh_listeners_reports_a_registration_a_peer_took(
    redis: fake_aioredis.FakeRedis,
) -> None:
    coord, peer = _coord(redis), _coord(redis)
    lost: list[tuple[ListenerKey, str]] = []
    coord.on_listener_lost = lambda key, owner_id: lost.append((key, owner_id))
    await coord.register_listener(ListenerKey(1), "a", replace=False)
    await coord.register_listener(ListenerKey(2), "b", replace=False)
    await peer.register_listener(ListenerKey(1), "peer", replace=True)

    await coord.refresh_listeners()

    assert lost == [(ListenerKey(1), "a")]
    assert list(coord._owned_listeners.values()) == [(ListenerKey(2), "b")]
    assert await redis.get(coord._listener_key(ListenerKey(1))) == b"peer"


async def test_refresh_listeners_keeps_a_newer_own_registration(
    redis: fake_aioredis.FakeRedis,
) -> None:
    coord = _coord(redis)
    await coord.register_listener(ListenerKey(1), "a", replace=False)
    await redis.set(coord._listener_key(ListenerKey(1)), "peer")
    script = coord._script(coord.LUA_REFRESH_LISTENERS_SCRIPT)

    async def refresh_then_reregister(**kw: Any) -> Any:
        lost = await script(**kw)
        await coord.register_listener(ListenerKey(1), "newer", replace=True)
        return lost

    coord._scripts[coord.LUA_REFRESH_LISTENERS_SCRIPT] = refresh_then_reregister  # ty: ignore[invalid-assignment]
    await coord.refresh_listeners()

    assert list(coord._owned_listeners.values()) == [(ListenerKey(1), "newer")]


async def test_refresh_listeners_without_registrations_touches_nothing(
    redis: fake_aioredis.FakeRedis,
) -> None:
    coord = _coord(redis)

    assert await coord.refresh_listeners() is None
    assert coord._scripts == {}


async def test_renew_forever_logs_a_failed_renewal(
    redis: fake_aioredis.FakeRedis, caplog: pytest.LogCaptureFixture
) -> None:
    coord = _coord(redis, listener_ttl=0.03)
    renewed = asyncio.Event()

    async def boom() -> None:
        renewed.set()
        msg = "down"
        raise RuntimeError(msg)

    coord.refresh_listeners = boom  # ty: ignore[invalid-assignment]
    task = asyncio.create_task(coord._renew_forever())
    try:
        await asyncio.wait_for(renewed.wait(), 1)
        await asyncio.sleep(0.03)
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)

    assert "Failed to renew Message listener registrations" in caplog.text


async def test_start_renews_registrations_until_stop(redis: fake_aioredis.FakeRedis) -> None:
    coord = _coord(redis, listener_ttl=0.15)
    await coord.start()
    try:
        await coord.register_listener(ListenerKey(1), "x", replace=False)
        await asyncio.sleep(0.3)

        assert await coord.listener_owners([ListenerKey(1)]) == ["x"]
    finally:
        await coord.stop()

    assert coord._heartbeat is None


async def test_start_replaces_a_fingerprint_a_registration_carries(
    redis: fake_aioredis.FakeRedis,
) -> None:
    coord = _coord(redis)
    taken = coord.fingerprint
    await redis.set(coord._listener_key(ListenerKey(1)), f"{taken}:other-session")

    await coord.start()
    try:
        assert coord.fingerprint != taken
    finally:
        await coord.stop()


async def test_stop_deletes_only_the_registrations_this_coordinator_holds(
    redis: fake_aioredis.FakeRedis,
) -> None:
    coord, peer = _coord(redis), _coord(redis)
    await coord.register_listener(ListenerKey(1), coord.new_owner_id(), replace=False)
    await peer.register_listener(ListenerKey(2), peer.new_owner_id(), replace=False)

    await coord.stop()

    assert await coord.listener_owners([ListenerKey(1)]) == [None]
    assert (await coord.listener_owners([ListenerKey(2)]))[0] is not None
    assert coord._owned_listeners == {}


def test_all_exports_only_the_coordinator() -> None:
    assert redis_update_coordinator.__all__ == ("RedisUpdateCoordinator",)
