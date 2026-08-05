"""Dispatcher coordination pipeline: lock lifecycle and key-cache hygiene.

These cover `Dispatcher.handle_update`, which drives the distributed lock and
was previously untested — both audit findings C1 and H3 lived here.
"""

import asyncio
import gc
from types import SimpleNamespace

import pytest

from pyrogram.types import Message

from pyroflow.dispatcher import Dispatcher
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
