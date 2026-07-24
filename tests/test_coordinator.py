"""Tests for the distributed-lock coordination subsystem.

Exercises the in-memory coordinator's state machine directly, plus the
UpdateCoordinated wrappers — including a regression guard for finding C3
(CallbackQueryCoordinated._is_coordinatable must return True).
"""

import pytest

from pyrogram.types import Message

from pyroflow import CallbackQueryCoordinated, MessageCoordinated
from pyroflow.enums import UpdateLockState
from pyroflow.update_coordinator.memory_update_coordinator import (
    MemoryUpdateCoordinator,
)

from .conftest import make_callback_query, make_message


# --- MemoryUpdateCoordinator state machine --------------------------------


def _coord():
    return MemoryUpdateCoordinator(Message, sleep=0.01, blocking_timeout=0.05)


async def test_acquire_first_time_succeeds():
    coord = _coord()
    assert await coord.acquire((1, 2)) is True


async def test_acquire_while_processing_times_out():
    coord = _coord()
    assert await coord.acquire((1, 2)) is True
    # second acquirer sees PROCESSING and never gets it → TimeoutError
    with pytest.raises(TimeoutError):
        await coord.acquire((1, 2))


async def test_acquire_after_handled_returns_false():
    coord = _coord()
    await coord.acquire((1, 2))
    await coord.release((1, 2), UpdateLockState.HANDLED)
    # already handled → skip (False), never blocks
    assert await coord.acquire((1, 2)) is False


async def test_release_with_none_frees_for_retry():
    coord = _coord()
    await coord.acquire((1, 2))
    await coord.release((1, 2), None)  # failed → allow retry
    assert await coord.acquire((1, 2)) is True


async def test_distinct_keys_are_independent():
    coord = _coord()
    assert await coord.acquire((1, 2)) is True
    assert await coord.acquire((3, 4)) is True


# --- UpdateCoordinated wrappers -------------------------------------------


async def test_message_coordinated_acquire_release_flow(raw_message_factory):
    mc = MessageCoordinated()  # default in-memory coordinator
    msg = raw_message_factory()

    assert await mc.is_coordinatable(msg) is True
    first = await mc.acquire(msg)
    assert first is True
    await mc.release(msg, UpdateLockState.HANDLED)


async def test_message_coordinated_key_cached_then_evicted(raw_message_factory):
    mc = MessageCoordinated()
    msg = raw_message_factory()
    key = await mc.extract_key(msg)
    assert id(msg) in mc._key_cache
    await mc.release(msg, None)  # release evicts the cached key
    assert id(msg) not in mc._key_cache
    assert isinstance(key, tuple)


async def test_callback_coordinated_is_coordinatable_returns_true():
    """Regression guard for C3: a missing ``return`` made this yield None,
    silently disabling CallbackQuery coordination entirely."""
    cc = CallbackQueryCoordinated()
    cbq = make_callback_query()
    result = await cc.is_coordinatable(cbq)
    assert result is True, (
        "CallbackQueryCoordinated._is_coordinatable must RETURN True "
        "(audit finding C3 regression)"
    )


async def test_callback_coordinated_extract_key():
    cc = CallbackQueryCoordinated()
    cbq = make_callback_query()
    assert await cc.extract_key(cbq) == (cbq.id,)


async def test_callback_coordinated_actually_acquires():
    """Because C3 is fixed, acquire() must reach the coordinator and return
    a real bool, not None (which would mean 'coordination skipped')."""
    cc = CallbackQueryCoordinated()
    cbq = make_callback_query()
    acquired = await cc.acquire(cbq)
    assert acquired is True
    await cc.release(cbq, UpdateLockState.HANDLED)
