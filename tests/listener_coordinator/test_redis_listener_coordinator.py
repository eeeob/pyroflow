"""Cross-session listener coordination over a shared Redis.

Cancellation propagates between sessions asynchronously: `publish()` returns
once Redis has *dispatched* the signal, not once peers have applied it. These
tests pin down what must hold during that window, in both directions:

  * a superseded listener must not resolve an update it no longer owns
    (otherwise two sessions deliver the same update);
  * a delayed signal must not cancel a newer listener that merely reuses the
    same key (otherwise a valid `ask()` dies for no reason).

Both are settled by the `coordinator_id` generation token rather than by
waiting for delivery, so they hold even if a signal is late or lost.
"""

from __future__ import annotations as _annotations

import asyncio
import logging
from functools import partial
from typing import TYPE_CHECKING, Any

import pytest

fakeredis = pytest.importorskip("fakeredis")
pytest.importorskip("lupa")  # fakeredis needs lupa to run Lua scripts

from fakeredis import aioredis as fake_aioredis  # noqa: E402

from pyroflow.errors import ListenerCancelled, UnresolvedUpdate  # noqa: E402
from pyroflow.listener_coordinator import redis_listener_coordinator as module  # noqa: E402
from pyroflow.listener_coordinator.listener_coordinator import ListenerCoordinator  # noqa: E402
from pyroflow.listener_coordinator.redis_listener_coordinator import (  # noqa: E402
    RedisListenerCoordinator,
)
from pyroflow.models import ListenerKey  # noqa: E402
from pyroflow.update_listener import MessageListener  # noqa: E402

from pyrogram.types import CallbackQuery, Message  # noqa: E402
from redis.exceptions import LockError  # noqa: E402

from ..conftest import make_message  # noqa: E402

if TYPE_CHECKING:
    from collections.abc import AsyncIterator


CHAT, USER = 100, 7
KEY = ListenerKey(CHAT, USER)


@pytest.fixture
async def redis() -> AsyncIterator[fake_aioredis.FakeRedis]:
    server = fake_aioredis.FakeRedis()
    try:
        yield server
    finally:
        await server.aclose()


@pytest.fixture
async def sessions(redis: fake_aioredis.FakeRedis) -> AsyncIterator[list[MessageListener]]:
    """Two independent listeners sharing one Redis, as in a multi-server deploy."""
    made = [
        MessageListener(coordinator_factory=partial(RedisListenerCoordinator, redis))
        for _ in range(2)
    ]
    for listener in made:
        await listener.start()
    try:
        yield made
    finally:
        for listener in made:
            listener.listeners.clear()
            await listener.coordinator.stop()


async def _quiesce() -> None:
    """Yield enough for pub/sub delivery and dispatched cancels to settle."""
    for _ in range(10):
        await asyncio.sleep(0)
    await asyncio.sleep(0.05)


# --- direction 1: a superseded listener must not resolve -----------------


async def _silence_cancel_signals(listener: MessageListener) -> None:
    """Stop this session from applying cancel signals.

    Models the case the fencing exists for: the signal is lost, dropped, or
    still queued behind a backed-up receiver. The session keeps a live local
    listener while no longer owning the registration.
    """
    task = listener.coordinator.listening_task
    if task is not None and not task.done():
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
    listener.coordinator.listening_task = None


async def test_superseded_listener_refuses_to_resolve(sessions: list[MessageListener]) -> None:
    """Session A takes the key over from B, but B never gets the signal. B
    still holds a live local listener — and must still refuse to deliver the
    update, because it no longer owns the registration."""
    a, b = sessions

    b_task = asyncio.ensure_future(b.listen(CHAT, USER, timeout=5))
    await _quiesce()
    assert KEY in b.listeners

    await _silence_cancel_signals(b)

    # A takes the key over.
    await a.coordinator.cancel(KEY)
    a_id = await a.coordinator.register(KEY)
    await _quiesce()

    # B's listener really is still live and untouched.
    stale = b.listeners.get(KEY)
    assert stale is not None and not stale.done()
    assert stale.coordinator_id != a_id

    # An update reaches B. Local state says "mine"; ownership says otherwise.
    with pytest.raises(UnresolvedUpdate):
        await b.resolve(make_message(CHAT, USER, 5))

    assert not b_task.done() or b_task.exception() is not None
    b_task.cancel()
    await asyncio.gather(b_task, return_exceptions=True)


async def test_owner_still_resolves_normally(sessions: list[MessageListener]) -> None:
    """The fencing check must not get in the way of the happy path."""
    a, _ = sessions
    task = asyncio.ensure_future(a.listen(CHAT, USER, timeout=5))
    await _quiesce()

    await a.resolve(make_message(CHAT, USER, 5))
    got = await asyncio.wait_for(task, 1)
    assert got.id == 5


# --- direction 2: a stale signal must not cancel a newer listener --------


async def test_stale_cancel_signal_spares_a_newer_listener(sessions: list[MessageListener]) -> None:
    """The signal for generation N must not cancel generation N+1, which may
    have registered while that signal was still in flight."""
    _, b = sessions

    first = asyncio.ensure_future(b.listen(CHAT, USER, timeout=5))
    await _quiesce()
    old_token = b.listeners[KEY].coordinator_id

    # That listener ends and a brand-new one takes its place locally.
    await b._cancel(KEY, cancel_coordinator=True)
    with pytest.raises(ListenerCancelled):
        await first

    second = asyncio.ensure_future(b.listen(CHAT, USER, timeout=5))
    await _quiesce()
    new_token = b.listeners[KEY].coordinator_id
    assert new_token != old_token

    # The delayed signal for the *first* generation finally lands.
    cancelled = await b.cancel(KEY, cancel_coordinator=False, coordinator_id=old_token)

    assert cancelled is False
    assert not second.done(), "a stale signal must not cancel a newer listener"
    assert b.listeners[KEY].coordinator_id == new_token

    second.cancel()
    await asyncio.gather(second, return_exceptions=True)


async def test_matching_cancel_signal_still_cancels(sessions: list[MessageListener]) -> None:
    """The guard must not make cancellation ineffective for its real target."""
    _, b = sessions

    task = asyncio.ensure_future(b.listen(CHAT, USER, timeout=5))
    await _quiesce()
    token = b.listeners[KEY].coordinator_id

    cancelled = await b.cancel(KEY, cancel_coordinator=False, coordinator_id=token)

    assert cancelled is True
    with pytest.raises(ListenerCancelled):
        await asyncio.wait_for(task, 1)


# --- lock bounds ----------------------------------------------------------


async def test_lock_always_carries_both_timeouts(sessions: list[MessageListener]) -> None:
    """redis-py defaults both to None. A lock with no TTL outlives the session
    that took it — a process dying mid-critical-section would leave that chat
    locked in Redis permanently — and a waiter with no blocking timeout hangs
    instead of failing. Neither may ever be None, including on the default
    construction the README shows."""
    a, _ = sessions
    lock = a.coordinator.lock(CHAT)

    assert lock.timeout is not None, "lock has no TTL: a dead holder locks the chat forever"
    assert lock.blocking_timeout is not None, "waiter would block forever"
    assert lock.blocking_timeout <= lock.timeout, (
        "a waiter must not outlast the TTL it is waiting on"
    )


async def test_lock_acquire_fails_fast_instead_of_hanging(redis: fake_aioredis.FakeRedis) -> None:
    """Contention must surface as a recoverable error, not a silent stall."""
    listener = MessageListener(
        coordinator_factory=partial(
            RedisListenerCoordinator,
            redis,
            lock_timeout=1,
            lock_blocking_timeout=0.2,
        )
    )
    held = listener.coordinator.lock(CHAT)
    await held.acquire()

    async def _contend() -> None:
        async with listener.coordinator.lock(CHAT):
            pass

    # wait_for is the safety net: if blocking_timeout ever regresses to None
    # this would hang forever, which would wedge CI instead of reporting.
    try:
        await asyncio.wait_for(_contend(), timeout=5)
    except LockError:
        pass  # expected: gave up cleanly
    except asyncio.TimeoutError:
        pytest.fail("lock acquire blocked indefinitely: blocking_timeout not applied")
    else:
        pytest.fail("acquired a lock that was already held")


async def test_lock_ttl_reclaims_an_abandoned_lock(redis: fake_aioredis.FakeRedis) -> None:
    """A holder that dies without releasing must not lock the chat forever."""
    listener = MessageListener(
        coordinator_factory=partial(
            RedisListenerCoordinator,
            redis,
            lock_timeout=0.3,
            lock_blocking_timeout=2,
        )
    )
    abandoned = listener.coordinator.lock(CHAT)
    await abandoned.acquire()  # never released, as if the session died

    async def _reclaim() -> None:
        async with listener.coordinator.lock(CHAT):
            pass  # reclaimed once the TTL lapses

    try:
        await asyncio.wait_for(_reclaim(), timeout=5)
    except asyncio.TimeoutError:
        pytest.fail("abandoned lock was never reclaimed: no TTL on the lock")


async def test_stop_propagates_its_own_cancellation(redis: fake_aioredis.FakeRedis) -> None:
    """stop() waits for the listening task to clean up; if stop() itself is
    cancelled meanwhile, the caller must see that cancellation, not lose it."""
    listener = MessageListener(coordinator_factory=partial(RedisListenerCoordinator, redis))
    coordinator = listener.coordinator
    assert isinstance(coordinator, RedisListenerCoordinator)
    await coordinator.start()
    await _silence_cancel_signals(listener)

    async def _slow_cleanup() -> None:
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            await asyncio.sleep(0.05)
            raise

    coordinator.listening_task = asyncio.create_task(_slow_cleanup())
    await asyncio.sleep(0)

    stopping = asyncio.create_task(coordinator.stop())
    await asyncio.sleep(0.01)  # stop() is now waiting on the cleanup
    stopping.cancel()
    try:
        with pytest.raises(asyncio.CancelledError):
            await stopping
    finally:
        await asyncio.gather(coordinator.listening_task, return_exceptions=True)
        await coordinator.pubsub.aclose()


# --- unit tests of each element --------------------------------------------

LOGGER = "pyroflow.listener_coordinator.redis_listener_coordinator"


class _FakeListener:
    """Stands in for an `UpdateListener`: records the cancels it receives."""

    __update_type__: Any = Message

    def __init__(self, error: Exception | None = None, gate: asyncio.Event | None = None) -> None:
        self.cancels: list[tuple[ListenerKey, dict[str, Any]]] = []
        self.error = error
        self.gate = gate

    async def cancel(self, key: ListenerKey, **kw: Any) -> bool:
        if self.gate is not None:
            await self.gate.wait()
        self.cancels.append((key, kw))
        if self.error is not None:
            raise self.error
        return True


@pytest.fixture
async def coordinator(
    redis: fake_aioredis.FakeRedis,
) -> AsyncIterator[RedisListenerCoordinator]:
    made = RedisListenerCoordinator(redis, _FakeListener())  # type: ignore[arg-type]
    try:
        yield made
    finally:
        made._owned_registrations.clear()
        await made.stop()


async def _wait_for(predicate: Any) -> None:
    for _ in range(100):
        if predicate():
            return
        await asyncio.sleep(0.01)
    pytest.fail("condition was never met")


def test_module_exports_and_logger() -> None:
    assert module.__all__ == ("RedisListenerCoordinator",)
    assert module.log.name == LOGGER


# --- class attributes and Lua scripts ---------------------------------------


async def test_lua_unregister_script(coordinator: RedisListenerCoordinator) -> None:
    redis = coordinator.redis
    script = coordinator.lua_unregister
    assert script is not None

    assert await script(keys=["k"], args=["a"], client=redis) == 1, "missing key counts as gone"

    await redis.set("k", "a")
    assert await script(keys=["k"], args=["b"], client=redis) == 0
    assert await redis.get("k") == b"a"

    assert await script(keys=["k"], args=["a"], client=redis) == 1
    assert await redis.exists("k") == 0


async def test_lua_bulk_unregister_script(coordinator: RedisListenerCoordinator) -> None:
    redis = coordinator.redis
    script = coordinator.lua_bulk_unregister
    assert script is not None
    await redis.set("k1", "a")
    await redis.set("k2", "other")

    deleted = await script(keys=["k1", "k2", "k3"], args=["a", "b", "c"], client=redis)

    assert deleted == 1
    assert await redis.exists("k1") == 0
    assert await redis.get("k2") == b"other"


async def test_lua_getdel_script(coordinator: RedisListenerCoordinator) -> None:
    redis = coordinator.redis
    script = coordinator.lua_getdel
    assert script is not None

    assert await script(keys=["k"], client=redis) is None

    await redis.set("k", "a")
    assert await script(keys=["k"], client=redis) == b"a"
    assert await redis.exists("k") == 0


# --- __init__ / _register_scripts -------------------------------------------


def test_init_sets_names_and_state(redis: fake_aioredis.FakeRedis) -> None:
    listener = _FakeListener()
    coordinator = RedisListenerCoordinator(redis, listener)  # type: ignore[arg-type]

    assert isinstance(coordinator, ListenerCoordinator)
    assert coordinator.listener is listener
    assert coordinator.redis is redis
    assert coordinator.update_type_name == "Message"
    assert coordinator.cancel_channel_name == "cancel|listen|Message"
    assert coordinator.lock_timeout == 30
    assert coordinator.lock_blocking_timeout == 10
    assert coordinator.pubsub is None
    assert coordinator.listening_task is None
    assert coordinator._pending_cancels == set()
    assert coordinator._owned_registrations == {}
    assert coordinator.lua_unregister is not None
    assert coordinator.lua_bulk_unregister is not None
    assert coordinator.lua_getdel is not None


def test_init_names_follow_the_update_type(redis: fake_aioredis.FakeRedis) -> None:
    class _CallbackListener(_FakeListener):
        __update_type__ = CallbackQuery

    coordinator = RedisListenerCoordinator(
        redis,
        _CallbackListener(),  # type: ignore[arg-type]
        lock_timeout=5,
        lock_blocking_timeout=1,
    )

    assert coordinator.cancel_channel_name == "cancel|listen|CallbackQuery"
    assert coordinator._pack_key(KEY) == "listen|registry|CallbackQuery|100|7|_"
    assert (coordinator.lock_timeout, coordinator.lock_blocking_timeout) == (5, 1)


def test_register_scripts_keeps_scripts_already_set(
    coordinator: RedisListenerCoordinator,
) -> None:
    sentinel: Any = object()
    coordinator.lua_unregister = sentinel
    coordinator.lua_bulk_unregister = sentinel
    coordinator.lua_getdel = None

    coordinator._register_scripts()

    assert coordinator.lua_unregister is sentinel
    assert coordinator.lua_bulk_unregister is sentinel
    assert coordinator.lua_getdel is not None and coordinator.lua_getdel is not sentinel


# --- _pack_key / _unpack_key ------------------------------------------------


def test_pack_key_sections_and_null_components(coordinator: RedisListenerCoordinator) -> None:
    assert coordinator._pack_key(ListenerKey(1)) == "listen|registry|Message|1|_|_"
    assert coordinator._pack_key(ListenerKey(1, 2, 3), "lock") == "listen|lock|Message|1|2|3"
    assert coordinator._pack_key(ListenerKey(-100, None, 0)) == "listen|registry|Message|-100|_|0"


@pytest.mark.parametrize(
    "key",
    [ListenerKey(1), ListenerKey(1, 2), ListenerKey(-100, None, 3), ListenerKey(5, 0, 0)],
)
def test_unpack_key_round_trips(coordinator: RedisListenerCoordinator, key: ListenerKey) -> None:
    assert coordinator._unpack_key(coordinator._pack_key(key)) == key
    assert coordinator._unpack_key(coordinator._pack_key(key, "lock")) == key


# --- lock -------------------------------------------------------------------


def test_lock_normalises_every_key_form(coordinator: RedisListenerCoordinator) -> None:
    assert coordinator.lock(1).name == "listen|lock|Message|1|_|_"
    assert coordinator.lock((1, 2)).name == "listen|lock|Message|1|2|_"
    assert coordinator.lock(ListenerKey(1, 2, 3)).name == "listen|lock|Message|1|2|3"


def test_lock_passes_configured_timeouts(redis: fake_aioredis.FakeRedis) -> None:
    coordinator = RedisListenerCoordinator(
        redis,
        _FakeListener(),  # type: ignore[arg-type]
        lock_timeout=4,
        lock_blocking_timeout=2,
    )
    lock = coordinator.lock(1)

    assert (lock.timeout, lock.blocking_timeout) == (4, 2)
    assert lock.thread_local is False


async def test_lock_is_shared_across_coordinators(redis: fake_aioredis.FakeRedis) -> None:
    a = RedisListenerCoordinator(redis, _FakeListener(), lock_blocking_timeout=0.05)  # type: ignore[arg-type]
    b = RedisListenerCoordinator(redis, _FakeListener(), lock_blocking_timeout=0.05)  # type: ignore[arg-type]

    async with a.lock(1):
        assert await b.lock(1).acquire() is False
        assert await b.lock(2).acquire() is True


# --- register ---------------------------------------------------------------


async def test_register_stores_a_hex_uuid(coordinator: RedisListenerCoordinator) -> None:
    token = await coordinator.register(KEY)
    packed = coordinator._pack_key(KEY)

    assert isinstance(token, str)
    assert len(token) == 32
    int(token, 16)
    assert await coordinator.redis.get(packed) == token.encode()
    assert coordinator._owned_registrations == {packed: token}


async def test_register_refuses_a_key_any_session_holds(redis: fake_aioredis.FakeRedis) -> None:
    a = RedisListenerCoordinator(redis, _FakeListener())  # type: ignore[arg-type]
    b = RedisListenerCoordinator(redis, _FakeListener())  # type: ignore[arg-type]
    token = await a.register(KEY)

    with pytest.raises(KeyError, match="already registered"):
        await b.register(KEY)

    assert b._owned_registrations == {}
    assert await redis.get(a._pack_key(KEY)) == token.encode()


# --- unregister -------------------------------------------------------------


async def test_unregister_without_id_deletes_any(coordinator: RedisListenerCoordinator) -> None:
    await coordinator.register(KEY)

    assert await coordinator.unregister(KEY) is True
    assert await coordinator.registered(KEY) is False
    assert coordinator._owned_registrations == {}
    assert await coordinator.unregister(KEY) is False, "nothing left to delete"


async def test_unregister_with_matching_id(coordinator: RedisListenerCoordinator) -> None:
    token = await coordinator.register(KEY)

    assert await coordinator.unregister(KEY, token) is True
    assert await coordinator.registered(KEY) is False
    assert coordinator._owned_registrations == {}


async def test_unregister_with_other_id_keeps_everything(
    coordinator: RedisListenerCoordinator,
) -> None:
    token = await coordinator.register(KEY)

    assert await coordinator.unregister(KEY, "stale") is False
    assert await coordinator.registered(KEY, token) is True
    assert coordinator._owned_registrations == {coordinator._pack_key(KEY): token}


async def test_unregister_with_id_of_a_gone_key_is_true(
    coordinator: RedisListenerCoordinator,
) -> None:
    assert await coordinator.unregister(KEY, "whatever") is True


async def test_unregister_with_id_of_a_peer_registration(redis: fake_aioredis.FakeRedis) -> None:
    a = RedisListenerCoordinator(redis, _FakeListener())  # type: ignore[arg-type]
    b = RedisListenerCoordinator(redis, _FakeListener())  # type: ignore[arg-type]
    token = await a.register(KEY)

    assert await b.unregister(KEY, token) is True
    assert await a.registered(KEY) is False


async def test_unregister_with_id_requires_the_script(
    coordinator: RedisListenerCoordinator,
) -> None:
    await coordinator.register(KEY)
    coordinator.lua_unregister = None

    with pytest.raises(RuntimeError, match="unregister script"):
        await coordinator.unregister(KEY, "id")

    assert await coordinator.unregister(KEY) is True, "the no-id path needs no script"


# --- registered -------------------------------------------------------------


async def test_registered_with_bytes_values(coordinator: RedisListenerCoordinator) -> None:
    assert await coordinator.registered(KEY) is False
    assert await coordinator.registered(KEY, "id") is False

    token = await coordinator.register(KEY)

    assert await coordinator.registered(KEY) is True
    assert await coordinator.registered(KEY, token) is True
    assert await coordinator.registered(KEY, "other") is False
    assert await coordinator.registered(ListenerKey(CHAT)) is False


async def test_registered_with_decoded_responses() -> None:
    redis = fake_aioredis.FakeRedis(decode_responses=True)
    try:
        coordinator = RedisListenerCoordinator(redis, _FakeListener())  # type: ignore[arg-type]
        token = await coordinator.register(KEY)

        assert await coordinator.registered(KEY, token) is True
        assert await coordinator.registered(KEY, "other") is False
    finally:
        await redis.aclose()


# --- cancel -----------------------------------------------------------------


async def _published(redis: Any, channel: str, action: Any) -> list[Any]:
    pubsub = redis.pubsub()
    await pubsub.subscribe(channel)
    try:
        await action()
        payloads = []
        for _ in range(5):
            msg = await pubsub.get_message(ignore_subscribe_messages=True, timeout=0.02)
            if msg and msg["type"] == "message":
                payloads.append(msg["data"])
        return payloads
    finally:
        await pubsub.aclose()


async def test_cancel_missing_key_publishes_nothing(coordinator: RedisListenerCoordinator) -> None:
    result: list[bool] = []

    async def _cancel() -> None:
        result.append(await coordinator.cancel(KEY))

    payloads = await _published(coordinator.redis, coordinator.cancel_channel_name, _cancel)

    assert result == [False]
    assert payloads == []


async def test_cancel_deletes_and_publishes_exact_payload(
    coordinator: RedisListenerCoordinator,
) -> None:
    token = await coordinator.register(KEY)
    packed = coordinator._pack_key(KEY)
    result: list[bool] = []

    async def _cancel() -> None:
        result.append(await coordinator.cancel(KEY))

    payloads = await _published(coordinator.redis, coordinator.cancel_channel_name, _cancel)

    assert result == [True]
    assert payloads == [f"{packed}|{token}".encode()]
    assert await coordinator.registered(KEY) is False
    assert coordinator._owned_registrations == {}


async def test_cancel_with_decoded_responses() -> None:
    redis = fake_aioredis.FakeRedis(decode_responses=True)
    try:
        coordinator = RedisListenerCoordinator(redis, _FakeListener())  # type: ignore[arg-type]
        token = await coordinator.register(KEY)
        packed = coordinator._pack_key(KEY)

        async def _cancel() -> None:
            assert await coordinator.cancel(KEY) is True

        payloads = await _published(redis, coordinator.cancel_channel_name, _cancel)

        assert payloads == [f"{packed}|{token}"]
    finally:
        await redis.aclose()


async def test_cancel_requires_the_script(coordinator: RedisListenerCoordinator) -> None:
    await coordinator.register(KEY)
    coordinator.lua_getdel = None

    with pytest.raises(RuntimeError, match="getdel script"):
        await coordinator.cancel(KEY)

    assert await coordinator.registered(KEY) is True


# --- start ------------------------------------------------------------------


async def test_start_subscribes_and_runs_the_listening_task(
    coordinator: RedisListenerCoordinator, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.INFO, logger=LOGGER):
        await coordinator.start()
    await _quiesce()

    assert coordinator.pubsub is not None
    assert coordinator.listening_task is not None
    assert not coordinator.listening_task.done(), "subscribe messages must be skipped"
    [(_, count)] = await coordinator.redis.pubsub_numsub(coordinator.cancel_channel_name)
    assert count == 1
    assert "Subscribed to cancel channel" in caplog.text
    assert coordinator.listener.cancels == []  # type: ignore[attr-defined]


# --- _listen_for_cancel_signals / _apply_cancel_signal ----------------------


async def test_listen_requires_start(coordinator: RedisListenerCoordinator) -> None:
    with pytest.raises(RuntimeError, match="Call start"):
        await coordinator._listen_for_cancel_signals()


async def test_listen_applies_a_signal_to_the_local_listener(
    coordinator: RedisListenerCoordinator,
) -> None:
    listener: _FakeListener = coordinator.listener  # type: ignore[assignment]
    await coordinator.start()
    await _quiesce()

    key = ListenerKey(-100, None, 9)
    await coordinator.redis.publish(
        coordinator.cancel_channel_name, f"{coordinator._pack_key(key)}|tok"
    )
    await _wait_for(lambda: listener.cancels)

    assert listener.cancels == [(key, {"cancel_coordinator": False, "coordinator_id": "tok"})]
    await _wait_for(lambda: not coordinator._pending_cancels)


async def test_listen_skips_a_malformed_payload(
    coordinator: RedisListenerCoordinator, caplog: pytest.LogCaptureFixture
) -> None:
    listener: _FakeListener = coordinator.listener  # type: ignore[assignment]
    await coordinator.start()
    await _quiesce()

    with caplog.at_level(logging.WARNING, logger=LOGGER):
        await coordinator.redis.publish(coordinator.cancel_channel_name, "no-separator")
        await coordinator.redis.publish(
            coordinator.cancel_channel_name, f"{coordinator._pack_key(KEY)}|tok"
        )
        await _wait_for(lambda: listener.cancels)

    assert "Malformed cancel signal payload" in caplog.text
    assert listener.cancels == [(KEY, {"cancel_coordinator": False, "coordinator_id": "tok"})]
    assert coordinator.listening_task is not None and not coordinator.listening_task.done()


async def test_listen_does_not_wait_for_a_slow_cancel(redis: fake_aioredis.FakeRedis) -> None:
    gate = asyncio.Event()
    listener = _FakeListener(gate=gate)
    coordinator = RedisListenerCoordinator(redis, listener)  # type: ignore[arg-type]
    await coordinator.start()
    await _quiesce()
    try:
        for key in (KEY, ListenerKey(CHAT)):
            await redis.publish(coordinator.cancel_channel_name, f"{coordinator._pack_key(key)}|t")

        # Both signals are dispatched while the first cancel is still blocked.
        await _wait_for(lambda: len(coordinator._pending_cancels) == 2)
        gate.set()
        await _wait_for(lambda: len(listener.cancels) == 2)
    finally:
        gate.set()
        await coordinator.stop()


async def test_apply_cancel_signal_logs_failures(
    redis: fake_aioredis.FakeRedis, caplog: pytest.LogCaptureFixture
) -> None:
    coordinator = RedisListenerCoordinator(
        redis,
        _FakeListener(error=ValueError("boom")),  # type: ignore[arg-type]
    )

    with caplog.at_level(logging.ERROR, logger=LOGGER):
        await coordinator._apply_cancel_signal(KEY, "tok")

    [record] = caplog.records
    assert "Failed to apply cancel signal" in record.getMessage()
    assert record.exc_info is not None and isinstance(record.exc_info[1], ValueError)


# --- stop -------------------------------------------------------------------


async def test_stop_before_start_is_a_no_op(coordinator: RedisListenerCoordinator) -> None:
    await coordinator.stop()
    await coordinator.stop()

    assert coordinator.pubsub is None
    assert coordinator.listening_task is None


async def test_stop_cancels_the_task_and_closes_pubsub(
    coordinator: RedisListenerCoordinator,
) -> None:
    await coordinator.start()
    task = coordinator.listening_task
    assert task is not None

    await coordinator.stop()

    assert task.cancelled()
    assert coordinator.listening_task is None
    assert coordinator.pubsub is None
    [(_, count)] = await coordinator.redis.pubsub_numsub(coordinator.cancel_channel_name)
    assert count == 0


async def test_stop_drains_pending_cancels(coordinator: RedisListenerCoordinator) -> None:
    done: list[str] = []

    async def _cancel_ok() -> None:
        await asyncio.sleep(0.02)
        done.append("ok")

    async def _cancel_fails() -> None:
        raise ValueError

    coordinator._pending_cancels.update(
        {asyncio.create_task(_cancel_ok()), asyncio.create_task(_cancel_fails())}
    )

    await coordinator.stop()

    assert done == ["ok"]
    assert coordinator._pending_cancels == set()


async def test_stop_bulk_unregisters_only_still_owned_keys(
    coordinator: RedisListenerCoordinator, caplog: pytest.LogCaptureFixture
) -> None:
    other = ListenerKey(CHAT)
    await coordinator.register(KEY)
    await coordinator.register(other)
    # A peer took `other` over meanwhile; its registration must survive.
    await coordinator.redis.set(coordinator._pack_key(other), "peer")

    with caplog.at_level(logging.INFO, logger=LOGGER):
        await coordinator.stop()

    assert await coordinator.registered(KEY) is False
    assert await coordinator.registered(other, "peer") is True
    assert coordinator._owned_registrations == {}
    assert "stopped with pending registrations" in caplog.text
    assert "bulk-deleted 1 keys" in caplog.text


async def test_stop_logs_a_bulk_unregister_failure(
    coordinator: RedisListenerCoordinator, caplog: pytest.LogCaptureFixture
) -> None:
    await coordinator.register(KEY)

    async def _failing(**_: Any) -> int:
        raise ConnectionError

    coordinator.lua_bulk_unregister = _failing  # type: ignore[assignment]

    with caplog.at_level(logging.ERROR, logger=LOGGER):
        await coordinator.stop()

    assert "Failed to bulk unregister keys during stop" in caplog.text
    assert coordinator._owned_registrations == {}


async def test_stop_requires_the_bulk_script_when_keys_remain(
    coordinator: RedisListenerCoordinator,
) -> None:
    coordinator.lua_bulk_unregister = None
    await coordinator.stop()  # nothing owned: the script is not needed

    await coordinator.register(KEY)
    with pytest.raises(RuntimeError, match="bulk unregister script"):
        await coordinator.stop()
