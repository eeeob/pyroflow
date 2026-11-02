"""Tests for the in-memory coordinator backend.

Coordination is two independent primitives, and these tests keep them
independent: a plain mutex (``lock``) that serialises whatever scope the
caller keys it by, and a flat handled registry (``is_handled`` /
``mark_handled``) whose membership is the entire state.

The pairing is what makes chat-wide ordering possible without losing
updates — the regression this whole design exists to prevent — and is
exercised end-to-end in test_dispatcher.py.
"""

from __future__ import annotations as _annotations

import asyncio
import gc

import pytest
from cachetools import TTLCache

from pyrogram.types import Message

from pyroflow.update_coordinator import memory_update_coordinator
from pyroflow.update_coordinator.memory_update_coordinator import (
    MemoryUpdateCoordinator,
    TimedLock,
)


# --- the lock: a plain mutex, nothing more --------------------------------


def _coord(**kw: float) -> MemoryUpdateCoordinator:
    kw.setdefault("blocking_timeout", 0.05)
    return MemoryUpdateCoordinator(Message, **kw)


async def test_lock_is_reusable_after_release() -> None:
    """The defining difference from the old design: releasing a lock leaves
    no trace, so the next caller takes it normally. The old coordinator
    remembered HANDLED forever and answered False to every later acquirer,
    which silently dropped every subsequent update in that scope."""
    coord = _coord()

    lock = coord.lock((1, 2))
    assert await lock.acquire() is True
    await lock.release()

    assert await coord.lock((1, 2)).acquire() is True, (
        "a released lock must be freely re-acquirable"
    )


async def test_lock_is_exclusive_while_held() -> None:
    coord = _coord()

    held = coord.lock((1, 2))
    assert await held.acquire() is True

    # Same scope, still held → the waiter gives up rather than proceeding.
    assert await coord.lock((1, 2)).acquire() is False


async def test_lock_scopes_are_independent() -> None:
    coord = _coord()
    assert await coord.lock((1, 2)).acquire() is True
    assert await coord.lock((3, 4)).acquire() is True


async def test_lock_wakes_a_waiter_on_release() -> None:
    coord = _coord(blocking_timeout=2)
    lock = coord.lock((1, 2))
    await lock.acquire()

    waiter = asyncio.create_task(coord.lock((1, 2)).acquire())
    await asyncio.sleep(0)
    assert not waiter.done(), "waiter should still be blocked"

    await lock.release()
    assert await waiter is True


async def test_holder_must_keep_the_lock_referenced() -> None:
    """Locks are held weakly, so an abandoned one is collected and the scope
    reopens. That is correct rather than a leak: releasing a lock requires a
    reference to it, so a locked-but-unreferenced lock could never have been
    released anyway — it would have wedged the scope forever.

    This pins the contract down, because the alternative failure is silent:
    callers must keep the lock alive for the whole critical section, which is
    exactly what `_CoordinatedRelease` does for the dispatcher."""
    coord = _coord(blocking_timeout=0.01)

    await coord.lock((1, 2)).acquire()  # reference dropped immediately
    gc.collect()

    assert await coord.lock((1, 2)).acquire() is True, (
        "an abandoned lock must not wedge its scope permanently"
    )


async def test_timed_lock_honours_its_timeout() -> None:
    lock = TimedLock(0.02)
    await lock.acquire()

    loop = asyncio.get_event_loop()
    started = loop.time()
    assert await lock.acquire() is False
    assert loop.time() - started >= 0.01


# --- the handled registry: membership is the whole state ------------------


async def test_mark_handled_then_is_handled() -> None:
    coord = _coord()
    await coord.mark_handled((1, 2))
    assert await coord.is_handled((1, 2)) is True


async def test_mark_handled_is_idempotent() -> None:
    coord = _coord()
    await coord.mark_handled((1, 2))
    await coord.mark_handled((1, 2))
    assert await coord.is_handled((1, 2)) is True


async def test_handled_keys_are_independent() -> None:
    coord = _coord()
    await coord.mark_handled((1, 2))
    assert await coord.is_handled((1, 3)) is False


async def test_handled_entries_expire() -> None:
    coord = _coord(handled_ttl=0.05)
    await coord.mark_handled((1, 2))
    assert await coord.is_handled((1, 2)) is True

    await asyncio.sleep(0.08)
    assert await coord.is_handled((1, 2)) is False


async def test_handled_registry_is_bounded() -> None:
    coord = _coord(max_handled=50, handled_ttl=3600)
    for i in range(500):
        await coord.mark_handled((1, i))

    assert len(coord.handled) <= 50


async def test_stop_clears_the_registry() -> None:
    coord = _coord()
    await coord.mark_handled((1, 2))
    await coord.stop()
    assert await coord.is_handled((1, 2)) is False


# --- the two primitives must not collide ----------------------------------


async def test_holding_a_lock_does_not_mark_it_handled() -> None:
    """By default the same tuple keys both, so without separate namespaces a
    held lock would read back as an already-handled update — and every
    update would be skipped the moment it was locked."""
    coord = _coord()
    await coord.lock((1, 2)).acquire()

    assert await coord.is_handled((1, 2)) is False


async def test_marking_handled_does_not_lock() -> None:
    coord = _coord()
    await coord.mark_handled((1, 2))

    assert await coord.lock((1, 2)).acquire() is True


# --- TimedLock on its own -------------------------------------------------


async def test_timed_lock_timeout_leaves_the_holder_in_place() -> None:
    lock = TimedLock(0.01)
    await lock.acquire()

    assert await lock.acquire() is False
    assert lock.locked()

    await lock.release()
    assert await lock.acquire() is True, "a timed-out waiter must not wedge the lock"


async def test_timed_lock_async_with_holds_then_releases() -> None:
    lock = TimedLock(0.05)

    async with lock as entered:
        assert entered is None
        assert lock.locked()

    assert not lock.locked()


async def test_timed_lock_timeout_error_names_the_timeout() -> None:
    lock = TimedLock(0.01)
    await lock.acquire()

    with pytest.raises(TimeoutError, match=r"Timeout waiting for lock after 0\.01s"):
        async with lock:
            pass


# --- MemoryUpdateCoordinator internals ------------------------------------


def test_init_bounds_the_registry_by_default() -> None:
    coord = MemoryUpdateCoordinator(Message, handled_ttl=12)

    assert isinstance(coord.handled, TTLCache)
    assert coord.handled.maxsize == 1000
    assert coord.handled.ttl == 12


def test_lock_is_a_timed_lock_with_the_coordinator_timeout() -> None:
    coord = _coord(blocking_timeout=0.3)
    lock = coord.lock((1, 2))

    assert isinstance(lock, TimedLock)
    assert lock.blocking_timeout == 0.3


def test_lock_is_shared_while_referenced() -> None:
    coord = _coord()
    lock = coord.lock((1, 2))

    assert coord.lock((1, 2)) is lock
    assert coord.lock((1, 3)) is not lock


async def test_stop_leaves_held_locks_alone() -> None:
    coord = _coord()
    lock = coord.lock((1, 2))
    await lock.acquire()

    await coord.stop()

    assert lock.locked()
    assert coord.lock((1, 2)) is lock


def test_all_exports_only_the_coordinator() -> None:
    assert memory_update_coordinator.__all__ == ("MemoryUpdateCoordinator",)
