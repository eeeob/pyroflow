"""Tests for ``pyroflow.listener_coordinator.memory_listener_coordinator``."""

from __future__ import annotations as _annotations

import gc
import logging
import weakref

import pytest

from pyroflow.listener_coordinator import memory_listener_coordinator as module
from pyroflow.listener_coordinator.listener_coordinator import ListenerCoordinator
from pyroflow.listener_coordinator.memory_listener_coordinator import MemoryListenerCoordinator
from pyroflow.models import ListenerKey
from pyroflow.utils import AsyncioLock

KEY = ListenerKey(1, 2)
OTHER = ListenerKey(1, 3)


@pytest.fixture
def coordinator() -> MemoryListenerCoordinator:
    return MemoryListenerCoordinator(listener=None)  # type: ignore[arg-type]


def test_module_exports_and_logger() -> None:
    assert module.__all__ == ("MemoryListenerCoordinator",)
    assert module.log.name == "pyroflow.listener_coordinator.memory_listener_coordinator"


# --- __init__ ---------------------------------------------------------------


def test_init_starts_empty_and_binds_listener() -> None:
    listener = object()
    coordinator = MemoryListenerCoordinator(listener)  # type: ignore[arg-type]

    assert isinstance(coordinator, ListenerCoordinator)
    assert coordinator.listener is listener
    assert coordinator.data == {}
    assert len(coordinator.locks) == 0
    assert next(coordinator.counter) == 0


def test_instances_do_not_share_state() -> None:
    a = MemoryListenerCoordinator(None)  # type: ignore[arg-type]
    b = MemoryListenerCoordinator(None)  # type: ignore[arg-type]
    a._register(KEY)

    assert b.data == {}
    assert a.lock(1) is not b.lock(1)


# --- lock -------------------------------------------------------------------


def test_lock_is_cached_per_key(coordinator: MemoryListenerCoordinator) -> None:
    lock = coordinator.lock(1)

    assert isinstance(lock, AsyncioLock)
    assert coordinator.lock(1) is lock
    assert coordinator.lock(2) is not lock


def test_lock_is_dropped_once_unreferenced(coordinator: MemoryListenerCoordinator) -> None:
    ref = weakref.ref(coordinator.lock(1))
    gc.collect()

    assert ref() is None
    assert 1 not in coordinator.locks
    assert isinstance(coordinator.lock(1), AsyncioLock)


# --- _register --------------------------------------------------------------


def test_register_counts_up_from_zero(coordinator: MemoryListenerCoordinator) -> None:
    assert coordinator._register(KEY) == 0
    assert coordinator._register(OTHER) == 1
    assert coordinator.data == {KEY: 0, OTHER: 1}


def test_register_duplicate_raises_and_keeps_the_original(
    coordinator: MemoryListenerCoordinator,
) -> None:
    coordinator._register(KEY)

    with pytest.raises(KeyError, match="already registered"):
        coordinator._register(KEY)

    assert coordinator.data == {KEY: 0}
    # A rejected duplicate does not consume an id.
    assert coordinator._register(OTHER) == 1


def test_register_again_after_unregister_gets_a_new_id(
    coordinator: MemoryListenerCoordinator,
) -> None:
    first = coordinator._register(KEY)
    coordinator._unregister(KEY)

    assert coordinator._register(KEY) != first


# --- _unregister ------------------------------------------------------------


def test_unregister_missing_key_returns_true(coordinator: MemoryListenerCoordinator) -> None:
    assert coordinator._unregister(KEY) is True
    assert coordinator._unregister(KEY, coordinator_id=5) is True
    assert coordinator.data == {}


def test_unregister_without_id_removes_any(coordinator: MemoryListenerCoordinator) -> None:
    coordinator._register(KEY)

    assert coordinator._unregister(KEY) is True
    assert KEY not in coordinator.data


def test_unregister_with_matching_id_removes(coordinator: MemoryListenerCoordinator) -> None:
    coordinator._register(OTHER)
    _id = coordinator._register(KEY)

    assert coordinator._unregister(KEY, coordinator_id=_id) is True
    assert coordinator.data == {OTHER: 0}


def test_unregister_honours_a_zero_id(coordinator: MemoryListenerCoordinator) -> None:
    assert coordinator._register(KEY) == 0

    assert coordinator._unregister(KEY, coordinator_id=1) is False
    assert coordinator._unregister(KEY, coordinator_id=0) is True
    assert coordinator.data == {}


def test_unregister_with_other_id_keeps_registration(
    coordinator: MemoryListenerCoordinator,
) -> None:
    _id = coordinator._register(KEY)

    assert coordinator._unregister(KEY, coordinator_id=_id + 1) is False
    assert coordinator.data == {KEY: _id}


# --- _cancel ----------------------------------------------------------------


def test_cancel_removes_whatever_the_id(coordinator: MemoryListenerCoordinator) -> None:
    coordinator._register(OTHER)
    coordinator._register(KEY)

    assert coordinator._cancel(KEY) is True
    assert coordinator.data == {OTHER: 0}


def test_cancel_missing_key_returns_true(coordinator: MemoryListenerCoordinator) -> None:
    assert coordinator._cancel(KEY) is True


# --- _registered ------------------------------------------------------------


def test_registered_missing_key_is_false(coordinator: MemoryListenerCoordinator) -> None:
    assert coordinator._registered(KEY) is False
    assert coordinator._registered(KEY, coordinator_id=0) is False


def test_registered_checks_the_id_only_when_given(
    coordinator: MemoryListenerCoordinator,
) -> None:
    _id = coordinator._register(KEY)

    assert coordinator._registered(KEY) is True
    assert coordinator._registered(KEY, coordinator_id=_id) is True
    assert coordinator._registered(KEY, coordinator_id=_id + 1) is False
    assert coordinator._registered(OTHER) is False


def test_registered_matches_exact_key_only(coordinator: MemoryListenerCoordinator) -> None:
    coordinator._register(ListenerKey(1))

    assert coordinator._registered(ListenerKey(1, 2)) is False


# --- async API --------------------------------------------------------------


async def test_register_async_delegates(coordinator: MemoryListenerCoordinator) -> None:
    assert await coordinator.register(KEY) == 0
    assert await coordinator.register(OTHER) == 1

    with pytest.raises(KeyError):
        await coordinator.register(KEY)


async def test_unregister_async_delegates(coordinator: MemoryListenerCoordinator) -> None:
    _id = await coordinator.register(KEY)

    assert await coordinator.unregister(KEY, _id + 1) is False
    assert await coordinator.registered(KEY) is True
    assert await coordinator.unregister(KEY, _id) is True
    assert await coordinator.registered(KEY) is False
    assert await coordinator.unregister(KEY) is True


async def test_cancel_async_delegates(coordinator: MemoryListenerCoordinator) -> None:
    await coordinator.register(KEY)

    assert await coordinator.cancel(KEY) is True
    assert await coordinator.registered(KEY) is False
    assert await coordinator.cancel(KEY) is True


async def test_registered_async_delegates(coordinator: MemoryListenerCoordinator) -> None:
    assert await coordinator.registered(KEY) is False
    _id = await coordinator.register(KEY)

    assert await coordinator.registered(KEY) is True
    assert await coordinator.registered(KEY, _id) is True
    assert await coordinator.registered(KEY, _id + 1) is False


# --- stop -------------------------------------------------------------------


async def test_stop_clears_data_resets_counter_and_warns(
    coordinator: MemoryListenerCoordinator, caplog: pytest.LogCaptureFixture
) -> None:
    await coordinator.register(KEY)
    await coordinator.register(OTHER)

    with caplog.at_level(logging.WARNING, logger=module.log.name):
        await coordinator.stop()

    assert coordinator.data == {}
    assert await coordinator.register(KEY) == 0
    [record] = caplog.records
    assert record.levelno == logging.WARNING
    assert "pending registrations" in record.getMessage()
    assert repr(KEY) in record.getMessage()
    assert repr(OTHER) in record.getMessage()


async def test_stop_without_registrations_is_silent(
    coordinator: MemoryListenerCoordinator, caplog: pytest.LogCaptureFixture
) -> None:
    await coordinator.register(KEY)
    await coordinator.unregister(KEY)

    with caplog.at_level(logging.WARNING, logger=module.log.name):
        await coordinator.stop()

    assert caplog.records == []
    # The counter is reset even when nothing was pending.
    assert await coordinator.register(KEY) == 0
