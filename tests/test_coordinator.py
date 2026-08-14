"""Tests for the coordination subsystem.

Coordination is two independent primitives, and these tests keep them
independent: a plain mutex (``lock``) that serialises whatever scope the
caller keys it by, and a flat handled registry (``is_handled`` /
``mark_handled``) whose membership is the entire state.

The pairing is what makes chat-wide ordering possible without losing
updates — the regression this whole design exists to prevent — so it is
exercised end-to-end here as well as in test_dispatcher_coordination.py.
"""

import asyncio
import gc

import pytest

from pyrogram.types import Message
from pyrogram.utils import get_peer_id

from pyroflow import CallbackQueryCoordinated, MessageCoordinated
from pyroflow.update_coordinator.memory_update_coordinator import (
    MemoryUpdateCoordinator,
    TimedLock,
)

from .conftest import make_callback_query


# --- the lock: a plain mutex, nothing more --------------------------------


def _coord(**kw):
    kw.setdefault("blocking_timeout", 0.05)
    return MemoryUpdateCoordinator(Message, **kw)


async def test_lock_is_acquirable():
    coord = _coord()
    assert await coord.lock((1, 2)).acquire() is True


async def test_lock_is_reusable_after_release():
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


async def test_lock_is_exclusive_while_held():
    coord = _coord()

    held = coord.lock((1, 2))
    assert await held.acquire() is True

    # Same scope, still held → the waiter gives up rather than proceeding.
    assert await coord.lock((1, 2)).acquire() is False


async def test_lock_scopes_are_independent():
    coord = _coord()
    assert await coord.lock((1, 2)).acquire() is True
    assert await coord.lock((3, 4)).acquire() is True


async def test_lock_wakes_a_waiter_on_release():
    coord = _coord(blocking_timeout=2)
    lock = coord.lock((1, 2))
    await lock.acquire()

    waiter = asyncio.create_task(coord.lock((1, 2)).acquire())
    await asyncio.sleep(0)
    assert not waiter.done(), "waiter should still be blocked"

    await lock.release()
    assert await waiter is True


async def test_lock_returns_false_rather_than_raising_on_timeout():
    """redis-py's Lock reports failure by returning False; the in-memory one
    must agree, or the dispatcher would need two different error paths."""
    coord = _coord(blocking_timeout=0.01)

    held = coord.lock((1, 2))       # keep it alive — see the test below
    await held.acquire()

    assert await coord.lock((1, 2)).acquire() is False


async def test_async_with_raises_instead_of_running_unlocked():
    """asyncio.Lock.__aenter__ ignores acquire()'s return value, so a timed
    lock that merely returned False would let `async with` fall straight
    into the critical section holding nothing."""
    coord = _coord(blocking_timeout=0.01)

    held = coord.lock((1, 2))
    await held.acquire()

    with pytest.raises(TimeoutError):
        async with coord.lock((1, 2)):
            pytest.fail("entered the critical section without the lock")


async def test_holder_must_keep_the_lock_referenced():
    """Locks are held weakly, so an abandoned one is collected and the scope
    reopens. That is correct rather than a leak: releasing a lock requires a
    reference to it, so a locked-but-unreferenced lock could never have been
    released anyway — it would have wedged the scope forever.

    This pins the contract down, because the alternative failure is silent:
    callers must keep the lock alive for the whole critical section, which is
    exactly what `_CoordinatedRelease` does for the dispatcher."""
    coord = _coord(blocking_timeout=0.01)

    await coord.lock((1, 2)).acquire()      # reference dropped immediately
    gc.collect()

    assert await coord.lock((1, 2)).acquire() is True, (
        "an abandoned lock must not wedge its scope permanently"
    )


async def test_timed_lock_honours_its_timeout():
    lock = TimedLock(0.02)
    await lock.acquire()

    loop = asyncio.get_event_loop()
    started = loop.time()
    assert await lock.acquire() is False
    assert loop.time() - started >= 0.01


# --- the handled registry: membership is the whole state ------------------


async def test_unknown_key_is_not_handled():
    assert await _coord().is_handled((1, 2)) is False


async def test_mark_handled_then_is_handled():
    coord = _coord()
    await coord.mark_handled((1, 2))
    assert await coord.is_handled((1, 2)) is True


async def test_mark_handled_is_idempotent():
    coord = _coord()
    await coord.mark_handled((1, 2))
    await coord.mark_handled((1, 2))
    assert await coord.is_handled((1, 2)) is True


async def test_handled_keys_are_independent():
    coord = _coord()
    await coord.mark_handled((1, 2))
    assert await coord.is_handled((1, 3)) is False


async def test_handled_entries_expire():
    coord = _coord(handled_ttl=0.05)
    await coord.mark_handled((1, 2))
    assert await coord.is_handled((1, 2)) is True

    await asyncio.sleep(0.08)
    assert await coord.is_handled((1, 2)) is False


async def test_handled_registry_is_bounded():
    coord = _coord(max_handled=50, handled_ttl=3600)
    for i in range(500):
        await coord.mark_handled((1, i))

    assert len(coord.handled) <= 50


async def test_stop_clears_the_registry():
    coord = _coord()
    await coord.mark_handled((1, 2))
    await coord.stop()
    assert await coord.is_handled((1, 2)) is False


# --- the two primitives must not collide ----------------------------------


async def test_holding_a_lock_does_not_mark_it_handled():
    """By default the same tuple keys both, so without separate namespaces a
    held lock would read back as an already-handled update — and every
    update would be skipped the moment it was locked."""
    coord = _coord()
    await coord.lock((1, 2)).acquire()

    assert await coord.is_handled((1, 2)) is False


async def test_marking_handled_does_not_lock():
    coord = _coord()
    await coord.mark_handled((1, 2))

    assert await coord.lock((1, 2)).acquire() is True


def test_lock_and_handled_build_distinct_keys():
    coord = _coord()
    assert coord.build_key((1, 2), "lock") != coord.build_key((1, 2), "handled")


def test_build_key_namespaces_by_update_type():
    assert (
        MemoryUpdateCoordinator(Message).build_key((1,))
        != MemoryUpdateCoordinator(type("Other", (Message,), {})).build_key((1,))
    )


# --- the pairing: wide lock + narrow identity -----------------------------


async def test_chat_wide_lock_serialises_without_losing_updates():
    """The scenario the split exists for. Locking per chat while registering
    per message must process every update exactly once, one at a time.

    Sharing one key for both would make the first update register the whole
    chat as handled, and every update after it would be dropped."""
    coord = MemoryUpdateCoordinator(Message, blocking_timeout=5)

    processed = []
    concurrent = peak = 0

    async def process(message_id):
        nonlocal concurrent, peak

        lock = coord.lock((100,))                  # scope: the chat
        assert await lock.acquire() is True
        try:
            if await coord.is_handled((100, message_id)):   # identity: the message
                return

            concurrent += 1
            peak = max(peak, concurrent)
            await asyncio.sleep(0.01)
            processed.append(message_id)
            concurrent -= 1

            await coord.mark_handled((100, message_id))
        finally:
            await lock.release()

    await asyncio.gather(*(process(i) for i in range(10)))

    assert peak == 1, f"chat lock failed to serialise (peak concurrency {peak})"
    assert sorted(processed) == list(range(10)), "updates were lost"


async def test_wide_lock_still_deduplicates_each_update():
    coord = MemoryUpdateCoordinator(Message, blocking_timeout=5)

    runs = []

    async def process(message_id):
        lock = coord.lock((100,))
        await lock.acquire()
        try:
            if await coord.is_handled((100, message_id)):
                return
            runs.append(message_id)
            await coord.mark_handled((100, message_id))
        finally:
            await lock.release()

    await process(1)
    await process(1)
    await process(2)

    assert runs == [1, 2], "a redelivered update was processed twice"


# --- UpdateCoordinated wrappers -------------------------------------------


async def test_message_coordinated_defaults_lock_per_message(raw_message_factory):
    """The shipped default keeps both keys at the update's own granularity,
    so behaviour matches the pre-split library until a scope is chosen."""
    mc = MessageCoordinated()
    msg = raw_message_factory()

    assert await mc.is_coordinatable(msg) is True
    assert await mc.extract_key(msg) == await mc.extract_update_id(msg)


async def test_message_coordinated_lock_flow(raw_message_factory):
    mc = MessageCoordinated()
    msg = raw_message_factory()

    lock = await mc.lock(msg)
    assert await lock.acquire() is True
    await lock.release()

    update_id = await mc.extract_update_id(msg)
    assert await mc.coordinator.is_handled(update_id) is False
    await mc.coordinator.mark_handled(update_id)
    assert await mc.coordinator.is_handled(update_id) is True


async def test_extract_key_can_be_widened_without_touching_identity(
    raw_message_factory,
):
    mc = MessageCoordinated(
        extract_key_func=lambda u: (get_peer_id(u.raw.peer_id),)
    )
    first = raw_message_factory(message_id=1)
    second = raw_message_factory(message_id=2)

    # Same lock scope...
    assert await mc.extract_key(first) == await mc.extract_key(second)
    # ...but still distinct identities, so neither is dropped as a duplicate.
    assert await mc.extract_update_id(first) != await mc.extract_update_id(second)


async def test_callback_coordinated_is_coordinatable_returns_true():
    """Regression guard for C3: a missing ``return`` made this yield None,
    silently disabling CallbackQuery coordination entirely."""
    cc = CallbackQueryCoordinated()
    result = await cc.is_coordinatable(make_callback_query())

    assert result is True, (
        "CallbackQueryCoordinated._is_coordinatable must RETURN True "
        "(audit finding C3 regression)"
    )


async def test_callback_coordinated_keys():
    cc = CallbackQueryCoordinated()
    cbq = make_callback_query()

    assert await cc.extract_key(cbq) == (cbq.id,)
    assert await cc.extract_update_id(cbq) == (cbq.id,)


async def test_callback_coordinated_lock_flow():
    cc = CallbackQueryCoordinated()
    cbq = make_callback_query()

    lock = await cc.lock(cbq)
    assert await lock.acquire() is True
    await lock.release()
    assert await (await cc.lock(cbq)).acquire() is True


async def test_hooks_raise_when_not_supplied():
    """Every hook follows the same contract: override it or inject it."""

    class Bare(MessageCoordinated):
        pass

    bare = Bare()
    bare.is_coordinatable_func = None
    bare.extract_key_func = None
    bare.extract_update_id_func = None

    msg = make_callback_query().message

    for call in (bare.is_coordinatable, bare.extract_key, bare.extract_update_id):
        with pytest.raises(NotImplementedError):
            await call(msg)


# --- liveness (audit finding H1) -----------------------------------------


def test_blocking_timeout_default_is_short():
    """The dispatcher waits on the lock while holding its worker lock, so a
    contended update stalls every other update on that worker for the full
    timeout. The default must stay small."""
    coordinator = MemoryUpdateCoordinator(Message)

    assert coordinator.blocking_timeout <= 30, (
        f"blocking_timeout default is {coordinator.blocking_timeout}s — a "
        f"contended update would stall a whole worker for that long"
    )
