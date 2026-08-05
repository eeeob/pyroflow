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

import asyncio
from functools import partial

import pytest

fakeredis = pytest.importorskip("fakeredis")

from fakeredis import aioredis as fake_aioredis  # noqa: E402

from pyroflow.errors import ListenerCancelled, UnresolvedUpdate  # noqa: E402
from pyroflow.listener_coordinator.redis_listener_coordinator import (  # noqa: E402
    RedisListenerCoordinator,
)
from pyroflow.models import ListenerKey  # noqa: E402
from pyroflow.update_listener import MessageListener  # noqa: E402

from .conftest import make_message  # noqa: E402


CHAT, USER = 100, 7
KEY = ListenerKey(CHAT, USER)


@pytest.fixture
async def redis():
    server = fake_aioredis.FakeRedis()
    try:
        yield server
    finally:
        await server.aclose()


@pytest.fixture
async def sessions(redis):
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


async def _quiesce():
    """Yield enough for pub/sub delivery and dispatched cancels to settle."""
    for _ in range(10):
        await asyncio.sleep(0)
    await asyncio.sleep(0.05)


# --- direction 1: a superseded listener must not resolve -----------------


async def _silence_cancel_signals(listener):
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


async def test_superseded_listener_refuses_to_resolve(sessions):
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


async def test_owner_still_resolves_normally(sessions):
    """The fencing check must not get in the way of the happy path."""
    a, _ = sessions
    task = asyncio.ensure_future(a.listen(CHAT, USER, timeout=5))
    await _quiesce()

    await a.resolve(make_message(CHAT, USER, 5))
    got = await asyncio.wait_for(task, 1)
    assert got.id == 5


# --- direction 2: a stale signal must not cancel a newer listener --------


async def test_stale_cancel_signal_spares_a_newer_listener(sessions):
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
    cancelled = await b.cancel(
        KEY, cancel_coordinator=False, coordinator_id=old_token
    )

    assert cancelled is False
    assert not second.done(), "a stale signal must not cancel a newer listener"
    assert b.listeners[KEY].coordinator_id == new_token

    second.cancel()
    await asyncio.gather(second, return_exceptions=True)


async def test_matching_cancel_signal_still_cancels(sessions):
    """The guard must not make cancellation ineffective for its real target."""
    _, b = sessions

    task = asyncio.ensure_future(b.listen(CHAT, USER, timeout=5))
    await _quiesce()
    token = b.listeners[KEY].coordinator_id

    cancelled = await b.cancel(KEY, cancel_coordinator=False, coordinator_id=token)

    assert cancelled is True
    with pytest.raises(ListenerCancelled):
        await asyncio.wait_for(task, 1)


# --- cancel() contract ----------------------------------------------------


# --- lock bounds ----------------------------------------------------------


async def test_lock_always_carries_both_timeouts(sessions):
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


async def test_lock_acquire_fails_fast_instead_of_hanging(redis):
    """Contention must surface as a recoverable error, not a silent stall."""
    from redis.exceptions import LockError

    from pyroflow.update_listener import MessageListener

    listener = MessageListener(
        coordinator_factory=partial(
            RedisListenerCoordinator, redis,
            lock_timeout=1, lock_blocking_timeout=0.2,
        )
    )
    held = listener.coordinator.lock(CHAT)
    await held.acquire()

    async def _contend():
        async with listener.coordinator.lock(CHAT):
            pass

    # wait_for is the safety net: if blocking_timeout ever regresses to None
    # this would hang forever, which would wedge CI instead of reporting.
    try:
        await asyncio.wait_for(_contend(), timeout=5)
    except LockError:
        pass                            # expected: gave up cleanly
    except asyncio.TimeoutError:
        pytest.fail("lock acquire blocked indefinitely: blocking_timeout not applied")
    else:
        pytest.fail("acquired a lock that was already held")


async def test_lock_ttl_reclaims_an_abandoned_lock(redis):
    """A holder that dies without releasing must not lock the chat forever."""
    from pyroflow.update_listener import MessageListener

    listener = MessageListener(
        coordinator_factory=partial(
            RedisListenerCoordinator, redis,
            lock_timeout=0.3, lock_blocking_timeout=2,
        )
    )
    abandoned = listener.coordinator.lock(CHAT)
    await abandoned.acquire()          # never released, as if the session died

    async def _reclaim():
        async with listener.coordinator.lock(CHAT):
            pass                        # reclaimed once the TTL lapses

    try:
        await asyncio.wait_for(_reclaim(), timeout=5)
    except asyncio.TimeoutError:
        pytest.fail("abandoned lock was never reclaimed: no TTL on the lock")


async def test_cancel_reports_whether_a_registration_existed(sessions):
    a, _ = sessions
    assert await a.coordinator.cancel(KEY) is False, "nothing registered yet"

    await a.coordinator.register(KEY)
    assert await a.coordinator.cancel(KEY) is True
    assert await a.coordinator.registered(KEY) is False


async def test_cancel_signal_carries_the_invalidated_token(redis, sessions):
    """Peers can only guard the right generation if the signal names it."""
    a, _ = sessions

    pubsub = redis.pubsub()
    await pubsub.subscribe(a.coordinator.cancel_channel_name)
    await _quiesce()

    token = await a.coordinator.register(KEY)
    await a.coordinator.cancel(KEY)

    payload = None
    for _ in range(50):
        msg = await pubsub.get_message(ignore_subscribe_messages=True, timeout=0.05)
        if msg and msg["type"] == "message":
            payload = msg["data"]
            break
    await pubsub.aclose()

    assert payload is not None, "cancel() must publish a signal"
    if isinstance(payload, bytes):
        payload = payload.decode()
    assert payload.endswith(token)
