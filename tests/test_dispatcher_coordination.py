"""Dispatcher coordination pipeline: lock lifecycle and key-cache hygiene.

These cover `Dispatcher.handle_update`, which drives the distributed lock and
was previously untested — both audit findings C1 and H3 lived here.
"""

import asyncio
import gc
from types import SimpleNamespace

import pytest

from pyrogram.types import Message

from pyroflow.dispatcher import Dispatcher, mark_handled
from pyroflow.enums import UpdateLockState
from pyroflow.errors import UnhandledUpdate
from pyroflow.update_coordinated import MessageCoordinated
from pyroflow.update_coordinator.memory_update_coordinator import (
    MemoryUpdateCoordinator,
)

from .conftest import make_message


def make_coordinated(**kw):
    kw.setdefault("sleep", 0.01)
    kw.setdefault("blocking_timeout", 0.2)
    return MessageCoordinated(
        coordinator_factory=lambda ut: MemoryUpdateCoordinator(ut, **kw)
    )


def make_dispatcher(coordinated, handle_result):
    """A minimal stand-in exposing only what handle_update() touches."""
    fake = SimpleNamespace(coordinateds={Message: coordinated})

    async def _handle_update(packet, parsed_update, handler_type):
        if isinstance(handle_result, Exception):
            raise handle_result
        return handle_result

    fake._handle_update = _handle_update
    return fake


def coordinatable_message(message_id=5, chat_id=100, user_id=7):
    """A Message carrying the raw.peer_id that MessageCoordinated keys on."""
    msg = make_message(chat_id, user_id, message_id)
    msg.raw = SimpleNamespace(peer_id=SimpleNamespace(channel_id=chat_id))
    return msg


PACKET = (None, None, None)


async def _can_another_session_take(coordinated, msg):
    """True if the update is still up for grabs by a peer session."""
    return await coordinated.coordinator.acquire(await coordinated.extract_key(msg))


# --- lock release semantics ----------------------------------------------


async def test_handled_update_is_claimed_so_peers_skip_it():
    coordinated = make_coordinated()
    msg = coordinatable_message()
    await Dispatcher.handle_update(
        make_dispatcher(coordinated, (1, 0)), PACKET, msg, type(None)
    )
    assert await _can_another_session_take(coordinated, msg) is False


async def test_raising_handler_still_claims_the_update():
    """A handler that raised still *ran*: the update reached its owner, so
    replaying it on a peer would duplicate work rather than recover.
    `sum(result)` counts exc_count deliberately — see Dispatcher docs."""
    coordinated = make_coordinated()
    msg = coordinatable_message()
    await Dispatcher.handle_update(
        make_dispatcher(coordinated, (0, 2)), PACKET, msg, type(None)
    )
    assert await _can_another_session_take(coordinated, msg) is False


async def test_untouched_update_is_left_for_a_peer_to_retry():
    coordinated = make_coordinated()
    msg = coordinatable_message()
    await Dispatcher.handle_update(
        make_dispatcher(coordinated, (0, 0)), PACKET, msg, type(None)
    )
    assert await _can_another_session_take(coordinated, msg) is True


async def test_unhandled_update_hands_the_update_back():
    """Raising UnhandledUpdate stops this session and leaves the lock free."""
    coordinated = make_coordinated()
    msg = coordinatable_message()
    dispatcher = make_dispatcher(coordinated, UnhandledUpdate("not mine"))

    with pytest.raises(UnhandledUpdate):
        await Dispatcher.handle_update(dispatcher, PACKET, msg, type(None))

    assert await _can_another_session_take(coordinated, msg) is True


async def test_update_owned_by_a_peer_is_skipped():
    coordinated = make_coordinated()
    msg = coordinatable_message()
    # A peer already finished this update.
    await coordinated.coordinator.release(
        await coordinated.extract_key(msg), UpdateLockState.HANDLED
    )
    await coordinated._evict(msg)

    ran = False

    async def _handle_update(*a, **kw):
        nonlocal ran
        ran = True
        return (1, 0)

    fake = SimpleNamespace(coordinateds={Message: coordinated})
    fake._handle_update = _handle_update

    await Dispatcher.handle_update(fake, PACKET, msg, type(None))
    assert ran is False, "update already handled by a peer must not be reprocessed"


async def test_uncoordinated_update_type_passes_straight_through():
    fake = SimpleNamespace(coordinateds={})
    seen = []

    async def _handle_update(packet, parsed_update, handler_type):
        seen.append(parsed_update)
        return (1, 0)

    fake._handle_update = _handle_update
    msg = coordinatable_message()
    await Dispatcher.handle_update(fake, PACKET, msg, type(None))
    assert seen == [msg]


# --- early release via mark_handled() ------------------------------------


async def peer_view(coordinated, msg):
    """What a peer session sees if it tries this update *right now*.

    The three outcomes are exactly the three lock states that matter:

    ``"blocked"``  the lock is still held — the peer waits, then times out
    ``"claimed"``  released as HANDLED — the peer knows to skip it
    ``"free"``     released without a state — the peer may retry it
    """
    try:
        acquired = await coordinated.coordinator.acquire(
            await coordinated.extract_key(msg)
        )
    except TimeoutError:
        return "blocked"
    return "free" if acquired else "claimed"


def make_marking_dispatcher(coordinated, body):
    """A dispatcher whose _handle_update runs `body(peer)`.

    `peer` probes the lock from *inside* the handler, while it is still
    running — which is the whole window this feature is about.
    """
    fake = SimpleNamespace(coordinateds={Message: coordinated})

    async def _handle_update(packet, parsed_update, handler_type):
        return await body(lambda: peer_view(coordinated, parsed_update))

    fake._handle_update = _handle_update
    return fake


async def test_lock_is_held_for_the_whole_handler_by_default():
    """The baseline the feature departs from: without mark_handled() a slow
    handler keeps peers blocked for its entire duration."""
    coordinated = make_coordinated()
    msg = coordinatable_message()

    async def body(peer):
        await asyncio.sleep(0)
        assert await peer() == "blocked"
        return (1, 0)

    await Dispatcher.handle_update(
        make_marking_dispatcher(coordinated, body), PACKET, msg, type(None)
    )


async def test_mark_handled_frees_peers_before_the_handler_returns():
    """The point of the feature: lock hold time tracks how long the update
    takes to *claim*, not how long the handler takes to *finish*."""
    coordinated = make_coordinated()
    msg = coordinatable_message()

    async def body(peer):
        assert mark_handled() is True
        # Give the scheduled release a chance to run, as any awaiting handler
        # inevitably would.
        await asyncio.sleep(0)

        # Still inside the handler, yet the update is already settled: a peer
        # neither waits on us nor reprocesses it.
        assert await peer() == "claimed"

        await asyncio.sleep(0.05)       # the "slow job"
        return (0, 0)

    await Dispatcher.handle_update(
        make_marking_dispatcher(coordinated, body), PACKET, msg, type(None)
    )

    # (0, 0) would normally hand the update back for retry. The early mark
    # must win over that.
    assert await _can_another_session_take(coordinated, msg) is False


async def test_mark_handled_is_idempotent():
    coordinated = make_coordinated()
    msg = coordinatable_message()

    async def body(peer):
        assert mark_handled() is True
        assert mark_handled() is False, "second call must not release twice"
        return (1, 0)

    await Dispatcher.handle_update(
        make_marking_dispatcher(coordinated, body), PACKET, msg, type(None)
    )
    assert await _can_another_session_take(coordinated, msg) is False


async def test_mark_handled_survives_a_raising_handler():
    """Already released as HANDLED — an exception afterwards must not hand the
    update back to a peer that would redo the part already done."""
    coordinated = make_coordinated()
    msg = coordinatable_message()

    async def body(peer):
        mark_handled()
        await asyncio.sleep(0)
        raise RuntimeError("boom")

    with pytest.raises(RuntimeError):
        await Dispatcher.handle_update(
            make_marking_dispatcher(coordinated, body), PACKET, msg, type(None)
        )

    assert await _can_another_session_take(coordinated, msg) is False


async def test_mark_handled_works_from_a_sync_handler_in_the_executor():
    """Sync handlers run through to_thread, off the event loop. The release
    has to be scheduled thread-safely rather than awaited, which is why
    mark_handled() is a plain function."""
    coordinated = make_coordinated()
    msg = coordinatable_message()
    result = {}

    def sync_handler():
        result["marked"] = mark_handled()

    async def body(peer):
        await asyncio.to_thread(sync_handler)     # copies the context
        await asyncio.sleep(0)
        assert await peer() == "claimed"
        return (0, 0)

    await Dispatcher.handle_update(
        make_marking_dispatcher(coordinated, body), PACKET, msg, type(None)
    )

    assert result["marked"] is True
    assert await _can_another_session_take(coordinated, msg) is False


async def test_mark_handled_outside_update_processing_is_a_noop():
    assert mark_handled() is False


async def test_marker_does_not_leak_between_updates():
    """The ContextVar is reset per update; a handler for update B must not be
    able to release update A's lock."""
    coordinated = make_coordinated()
    first = coordinatable_message(message_id=1)

    async def body(peer):
        mark_handled()
        return (1, 0)

    await Dispatcher.handle_update(
        make_marking_dispatcher(coordinated, body), PACKET, first, type(None)
    )

    assert mark_handled() is False, "marker outlived the update it belonged to"


# --- key cache hygiene (audit finding C1) --------------------------------


async def test_key_cache_is_evicted_when_the_update_is_collected():
    """CPython recycles id() values, and the skip paths never reach
    release()/_evict(). A stale id-keyed entry could then be served to a
    *different* update landing at the same address — locking it under the
    wrong key and dropping it as a phantom duplicate."""
    coordinated = make_coordinated()
    msg = coordinatable_message(message_id=111)
    await coordinated.extract_key(msg)
    assert len(coordinated._key_cache) == 1

    del msg
    gc.collect()
    assert len(coordinated._key_cache) == 0


async def test_recycled_id_does_not_yield_a_stale_key():
    coordinated = make_coordinated()

    first = coordinatable_message(message_id=111)
    first_key = await coordinated.extract_key(first)
    first_id = id(first)
    del first
    gc.collect()

    # Allocate until CPython hands back that same address.
    for _ in range(20000):
        candidate = coordinatable_message(message_id=222)
        if id(candidate) == first_id:
            key = await coordinated.extract_key(candidate)
            assert key != first_key
            assert key[1] == 222, "stale cached key served to a different update"
            return
        del candidate

    pytest.skip("id() was not recycled within the sampling window")


async def test_skip_path_does_not_accumulate_cache_entries():
    coordinated = make_coordinated()

    for i in range(200):
        msg = coordinatable_message(message_id=i)
        await coordinated.coordinator.release(
            await coordinated.extract_key(msg), UpdateLockState.HANDLED
        )
        await coordinated._evict(msg)
        await Dispatcher.handle_update(
            make_dispatcher(coordinated, (1, 0)), PACKET, msg, type(None)
        )
        del msg

    gc.collect()
    assert len(coordinated._key_cache) == 0


# --- liveness (audit finding H1) -----------------------------------------


def test_blocking_timeout_default_is_short():
    """acquire() polls while the dispatcher holds its worker lock, so a
    contended update stalls every other update on that worker for the full
    timeout. The default must stay small."""
    coordinator = MemoryUpdateCoordinator(Message)
    assert coordinator.blocking_timeout <= 30, (
        f"blocking_timeout default is {coordinator.blocking_timeout}s — a "
        f"contended update would stall a whole worker for that long"
    )
