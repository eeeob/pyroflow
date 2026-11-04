"""Behavioural tests for UpdateListener and its coordinator.

Covers key matching and the default timeout using the real MessageListener
with the default in-memory coordinator (no network), then every
UpdateListener element directly through a minimal local subclass.
"""

from __future__ import annotations as _annotations

import asyncio
import logging
import threading
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
from typing import Any

import pytest
from pyrogram.types import CallbackQuery, Message

from pyroflow import MessageListener
from pyroflow.enums import DuplicatePolicy, ListenOutcome
from pyroflow.errors import ListenerAlreadyExists, ListenerCancelled, ListenerTimeout
from pyroflow.models import ListenerKey, ListenerModel
from pyroflow.update_coordinator import MemoryUpdateCoordinator
from pyroflow.update_listener import update_listener as update_listener_module
from pyroflow.update_listener.update_listener import UpdateListener

from ..conftest import make_message

PEER = "peer:1"
"""An owner id no coordinator of these tests issued."""


async def _started(listener: MessageListener) -> MessageListener:
    await listener.start()
    return listener


async def test_resolve_matches_less_specific_key() -> None:
    """A listener on (chat, user) matches an update with a message id via
    progressive ListenerKey.sub_keys() fallback."""
    lis = await _started(MessageListener())
    try:
        task = asyncio.ensure_future(lis.listen(100))  # chat-only listener
        await asyncio.sleep(0.02)
        await lis.resolve(make_message(100, 7, 5))
        got = await asyncio.wait_for(task, 1)
        assert got.chat.id == 100
    finally:
        await lis.stop()


async def test_resolve_matches_a_message_only_listener() -> None:
    """`listen(chat, None, message_id)` — "whoever answers *this* message,
    regardless of who they are" — is reached through the combination-based
    sub_keys(), which yields (chat, None, message) among the candidates."""
    lis = await _started(MessageListener())
    try:
        task = asyncio.ensure_future(lis.listen(100, None, 5, timeout=5))
        await asyncio.sleep(0.02)

        # An update from a user the listener never named.
        await lis.resolve(make_message(100, 7, 5))

        got = await asyncio.wait_for(task, 1)
        assert got.id == 5
    finally:
        await lis.stop()


async def test_user_listener_still_outranks_a_message_only_one() -> None:
    """Ordering is by specificity, then by field order: a (chat, user)
    listener keeps winning over a (chat, None, message) one."""
    lis = await _started(MessageListener())
    try:
        by_user = asyncio.ensure_future(lis.listen(100, 7, timeout=5))
        by_message = asyncio.ensure_future(lis.listen(100, None, 5, timeout=5))
        await asyncio.sleep(0.02)

        await lis.resolve(make_message(100, 7, 5))

        got = await asyncio.wait_for(by_user, 1)
        assert got.id == 5
        assert not by_message.done(), "the less specific listener was consumed"
    finally:
        by_message.cancel()
        await asyncio.gather(by_message, return_exceptions=True)
        await lis.stop()


async def test_listener_default_timeout_used_when_not_overridden() -> None:
    lis = await _started(MessageListener(timeout=0.05))
    try:
        with pytest.raises(ListenerTimeout):
            await lis.listen(300, 7)  # no per-call timeout → falls back to 0.05
    finally:
        await lis.stop()


# --- UpdateListener base: a local subclass exercises every hook directly ---


class _Listener(UpdateListener[Message]):
    __update_type__ = Message


def _key_of(update: Message) -> ListenerKey:
    return ListenerKey(update.chat.id, update.from_user.id, update.id)


def _make(**kw: Any) -> _Listener:
    kw.setdefault("extract_key_func", _key_of)
    return _Listener(**kw)


def _registry(lis: UpdateListener) -> dict[ListenerKey, str]:
    """The listener registry of the in-memory coordinator behind `lis`."""
    coordinator = lis.coordinator
    assert isinstance(coordinator, MemoryUpdateCoordinator)
    return coordinator.listeners


async def _pending(lis: UpdateListener, *args: Any, **kw: Any) -> asyncio.Task:
    task = asyncio.ensure_future(lis.listen(*args, **kw))
    await asyncio.sleep(0.01)
    return task


async def _drain(*tasks: asyncio.Future) -> None:
    for task in tasks:
        task.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)


async def _is_true(update: Message) -> bool:
    return True


async def _chat_key(update: Message) -> ListenerKey:
    return ListenerKey(update.chat.id)


def test_module_exports_and_logger() -> None:
    assert update_listener_module.__all__ == ("UpdateListener",)
    assert update_listener_module.log.name == "pyroflow.update_listener.update_listener"


# --- __init__ -----------------------------------------------------------------


def test_init_defaults() -> None:
    lis = _Listener()
    assert isinstance(lis.coordinator, MemoryUpdateCoordinator)
    assert lis.coordinator.update_type is Message
    assert lis.coordinator.on_listener_lost == lis.discard
    assert lis.duplicate_policy is DuplicatePolicy.REPLACE
    assert lis.extract_key_func is None
    assert lis.is_bypass_func is None
    assert lis.extract_lock_key_func is None
    assert lis.timeout is None
    assert lis.listeners == {}
    assert lis.is_closed is False


def test_init_stores_arguments() -> None:
    coordinator = MemoryUpdateCoordinator(Message)

    def bypass(update: Message) -> bool:
        return False

    def lock_key(key: ListenerKey) -> tuple[int]:
        return (key.chat_id,)

    lis = _Listener(
        coordinator=coordinator,
        duplicate_policy=DuplicatePolicy.REJECT,
        extract_key_func=_key_of,
        is_bypass_func=bypass,
        extract_lock_key_func=lock_key,
        timeout=3,
    )
    assert lis.coordinator is coordinator
    assert coordinator.on_listener_lost == lis.discard
    assert lis.duplicate_policy is DuplicatePolicy.REJECT
    assert lis.extract_key_func is _key_of
    assert lis.is_bypass_func is bypass
    assert lis.extract_lock_key_func is lock_key
    assert lis.timeout == 3


def test_init_rejects_a_coordinator_of_another_update_type() -> None:
    with pytest.raises(
        ValueError, match="needs a coordinator for Message, got one for CallbackQuery"
    ):
        _Listener(coordinator=MemoryUpdateCoordinator(CallbackQuery))


def test_init_rejects_a_coordinator_serving_another_listener() -> None:
    coordinator = MemoryUpdateCoordinator(Message)
    _Listener(coordinator=coordinator)

    with pytest.raises(ValueError, match="already serves another listener"):
        _Listener(coordinator=coordinator)


def test_init_passes_unknown_kwargs_up_the_mro() -> None:
    with pytest.raises(TypeError):
        _Listener(unknown=1)


# --- start / stop -------------------------------------------------------------


async def test_stop_cancels_every_listener_and_refuses_listen_until_start() -> None:
    lis = _make()
    first = await _pending(lis, 1)
    second = await _pending(lis, 2, 3)

    await lis.stop()

    for task in (first, second):
        with pytest.raises(ListenerCancelled):
            await task
    assert lis.listeners == {}
    assert lis.is_closed is True
    with pytest.raises(ListenerCancelled):
        await lis.listen(1)

    await lis.start()

    assert lis.is_closed is False
    with pytest.raises(ListenerTimeout):
        await lis.listen(1, timeout=0.01)


async def test_start_and_stop_leave_the_coordinator_alone() -> None:
    calls: list[str] = []

    class Coordinator(MemoryUpdateCoordinator):
        async def start(self) -> None:
            calls.append("start")

        async def stop(self) -> None:
            calls.append("stop")

    lis = _make(coordinator=Coordinator(Message))
    await lis.start()
    await lis.stop()

    assert calls == []


# --- discard / cancel / _forget ----------------------------------------------


async def test_discard_cancels_the_local_listener_only() -> None:
    lis = _make()
    task = await _pending(lis, 1)
    key = ListenerKey(1)

    assert lis.discard(key) is True
    assert key not in lis.listeners
    assert key in _registry(lis)  # the waiting `listen` unregisters it
    with pytest.raises(ListenerCancelled) as exc:
        await task
    assert exc.value.value == key
    assert exc.value.is_duplicate is False


async def test_discard_ignores_another_owner() -> None:
    lis = _make()
    task = await _pending(lis, 1)
    try:
        assert lis.discard(ListenerKey(1), PEER) is False
        assert not task.done()
        assert lis.discard(ListenerKey(1), lis.listeners[ListenerKey(1)].owner_id) is True
    finally:
        await _drain(task)


async def test_discard_marks_duplicates() -> None:
    lis = _make()
    task = await _pending(lis, 1)

    assert lis.discard(ListenerKey(1), is_duplicate=True) is True
    with pytest.raises(ListenerCancelled) as exc:
        await task
    assert exc.value.is_duplicate is True


async def test_discard_without_a_listener_is_false() -> None:
    lis = _make()
    lis.listeners[ListenerKey(2)] = done = ListenerModel(ListenerKey(2))
    done.resolve("update")

    assert lis.discard(ListenerKey(1)) is False
    assert lis.discard(ListenerKey(2)) is True  # an already finished future is left as it is
    assert await done.future == "update"


async def test_cancel_cancels_locally_and_in_the_coordinator() -> None:
    lis = _make()
    task = await _pending(lis, 1)

    assert await lis.cancel(ListenerKey(1)) is True
    with pytest.raises(ListenerCancelled):
        await task
    assert _registry(lis) == {}


async def test_cancel_removes_a_peer_registration() -> None:
    lis = _make()
    await lis.coordinator.register_listener(ListenerKey(1), PEER, replace=False)

    assert await lis.cancel(ListenerKey(1)) is True
    assert _registry(lis) == {}


async def test_cancel_without_any_listener_is_false() -> None:
    assert await _make().cancel(ListenerKey(1)) is False


async def test__forget_drops_only_that_listener() -> None:
    lis = _make()
    key = ListenerKey(1)
    current = ListenerModel(key)
    lis.listeners[key] = current

    lis._forget(key, ListenerModel(key))
    assert lis.listeners[key] is current

    lis._forget(key, current)
    assert lis.listeners == {}

    lis._forget(key, current)  # no listener left: a no-op
    assert lis.listeners == {}


# --- listen ---------------------------------------------------------------------


async def test_listen_registers_locally_and_in_the_coordinator() -> None:
    lis = _make()
    task = await _pending(lis, 1, 2, 3, {"step": 1}, prompt_id=9)
    key = ListenerKey(1, 2, 3)
    try:
        listener = lis.listeners[key]
        assert listener.key == key
        assert listener.meta == {"step": 1}
        assert listener.prompt_id == 9
        assert listener.owner_id is not None
        assert lis.coordinator.is_mine(listener.owner_id)
        assert _registry(lis) == {key: listener.owner_id}
    finally:
        await _drain(task)


async def test_listen_unregisters_after_resolution() -> None:
    lis = _make()
    task = await _pending(lis, 100, 7, 5)
    update = make_message(100, 7, 5)
    await lis.resolve(update)

    assert await task is update
    assert lis.listeners == {}
    assert _registry(lis) == {}


async def test_listen_replace_cancels_the_old_listener_and_keeps_the_new() -> None:
    lis = _make()
    first = await _pending(lis, 1)
    second = await _pending(lis, 1)
    try:
        with pytest.raises(ListenerCancelled) as exc:
            await first
        assert exc.value.is_duplicate is True

        # the old waiter's `unregister` must not delete the replacement
        assert _registry(lis) == {ListenerKey(1): lis.listeners[ListenerKey(1)].owner_id}
    finally:
        await _drain(second)


async def test_listen_replace_takes_over_a_peer_registration() -> None:
    lis = _make()
    await lis.coordinator.register_listener(ListenerKey(1), PEER, replace=False)
    task = await _pending(lis, 1)
    try:
        assert _registry(lis) == {ListenerKey(1): lis.listeners[ListenerKey(1)].owner_id}
    finally:
        await _drain(task)


async def test_listen_reject_leaves_the_first_listener_running() -> None:
    lis = _make(duplicate_policy=DuplicatePolicy.REJECT)
    first = await _pending(lis, 1)
    try:
        with pytest.raises(ListenerAlreadyExists) as exc:
            await lis.listen(1)
        assert exc.value.value == ListenerKey(1)
        assert not first.done()
        assert ListenerKey(1) in lis.listeners
    finally:
        await _drain(first)


async def test_listen_reject_ignores_a_finished_listener_still_returning() -> None:
    lis = _make(duplicate_policy=DuplicatePolicy.REJECT)
    lis.listeners[ListenerKey(1)] = finished = ListenerModel(ListenerKey(1))
    finished.resolve("update")

    task = await _pending(lis, 1)
    try:
        assert lis.listeners[ListenerKey(1)] is not finished
        assert not task.done()
    finally:
        await _drain(task)


async def test_listen_raises_when_the_lock_is_not_acquired() -> None:
    lis = _make(coordinator=MemoryUpdateCoordinator(Message, blocking_timeout=0.01))
    lock = lis.coordinator.lock((1,))
    await lock.acquire()
    try:
        with pytest.raises(TimeoutError):
            await lis.listen(1)
    finally:
        await lock.release()

    assert lis.listeners == {}
    assert _registry(lis) == {}


async def test_listen_reject_refuses_a_peer_registration() -> None:
    lis = _make(duplicate_policy=DuplicatePolicy.REJECT)
    await lis.coordinator.register_listener(ListenerKey(1), PEER, replace=False)

    with pytest.raises(ListenerAlreadyExists):
        await lis.listen(1)
    assert lis.listeners == {}
    assert _registry(lis) == {ListenerKey(1): PEER}


async def test_listen_reject_takes_over_its_own_leftover_registration() -> None:
    lis = _make(duplicate_policy=DuplicatePolicy.REJECT)
    leftover = lis.coordinator.new_owner_id()
    await lis.coordinator.register_listener(ListenerKey(1), leftover, replace=False)

    task = await _pending(lis, 1)
    try:
        assert _registry(lis) == {ListenerKey(1): lis.listeners[ListenerKey(1)].owner_id}
        assert _registry(lis)[ListenerKey(1)] != leftover
    finally:
        await _drain(task)


async def test_listen_registers_under_the_lock_an_update_holds() -> None:
    lis = _make()
    lock = lis.coordinator.lock((1,))  # strong reference: the coordinator holds locks weakly
    await lock.acquire()
    task = await _pending(lis, 1)
    try:
        assert ListenerKey(1) not in lis.listeners
        assert _registry(lis) == {}
    finally:
        await lock.release()

    await asyncio.sleep(0.01)
    try:
        assert ListenerKey(1) in _registry(lis)
    finally:
        await _drain(task)


async def test_listen_takes_the_lock_named_by_extract_lock_key() -> None:
    lis = _make(extract_lock_key_func=lambda key: (key.chat_id, key.user_id))
    lock = lis.coordinator.lock((1, 2))
    await lock.acquire()
    task = await _pending(lis, 1, 2)
    try:
        assert _registry(lis) == {}
    finally:
        await lock.release()
        await asyncio.sleep(0.01)
        await _drain(task)


async def test_listen_forgets_the_listener_when_registration_fails() -> None:
    class Failing(MemoryUpdateCoordinator):
        async def register_listener(self, *args: Any, **kw: Any) -> str | None:
            msg = "down"
            raise RuntimeError(msg)

    lis = _make(coordinator=Failing(Message))

    with pytest.raises(RuntimeError, match="down"):
        await lis.listen(1)
    assert lis.listeners == {}


async def test_listen_timeout_carries_the_key_and_cleans_up() -> None:
    lis = _make()
    with pytest.raises(ListenerTimeout) as exc:
        await lis.listen(1, 2, timeout=0.01)
    assert exc.value.value == ListenerKey(1, 2)
    assert exc.value.__suppress_context__ is True
    assert lis.listeners == {}
    assert _registry(lis) == {}


async def test_listen_per_call_timeout_overrides_the_default() -> None:
    lis = _make(timeout=10)
    with pytest.raises(ListenerTimeout):
        await asyncio.wait_for(lis.listen(1, timeout=0.01), 1)


async def test_listen_external_cancellation_propagates_and_cleans_up() -> None:
    lis = _make()
    task = await _pending(lis, 1)
    future = lis.listeners[ListenerKey(1)].future

    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert future.done()
    assert lis.listeners == {}
    assert _registry(lis) == {}


async def test_listen_logs_a_failed_unregister_and_keeps_the_result(
    caplog: pytest.LogCaptureFixture,
) -> None:
    class Failing(MemoryUpdateCoordinator):
        async def unregister_listener(self, *args: Any, **kw: Any) -> bool:
            msg = "down"
            raise RuntimeError(msg)

    lis = _make(coordinator=Failing(Message))
    task = await _pending(lis, 1)
    update = make_message(1)
    lis.listeners[ListenerKey(1)].resolve(update)

    with caplog.at_level(logging.ERROR, logger=update_listener_module.log.name):
        assert await task is update
    assert "Failed to unregister the listener for" in caplog.text


def test_call_is_listen() -> None:
    assert UpdateListener.__call__ is UpdateListener.listen


# --- resolve ----------------------------------------------------------------------


async def test_resolve_without_key_is_unmatched_and_skips_listeners() -> None:
    lis = _make(extract_key_func=lambda update: None)
    task = await _pending(lis, 100)
    try:
        assert await lis.resolve(make_message(100, 7, 5)) is ListenOutcome.UNMATCHED
        assert not task.done()
    finally:
        await _drain(task)


async def test_resolve_without_registration_is_unmatched() -> None:
    lis = _make()
    other = await _pending(lis, 999)
    try:
        assert await lis.resolve(make_message(100, 7, 5)) is ListenOutcome.UNMATCHED
        assert not other.done()
    finally:
        await _drain(other)


async def test_resolve_hands_the_update_to_its_listener_and_claims_it() -> None:
    lis = _make()
    task = await _pending(lis, 100, 7)
    update = make_message(100, 7, 5)

    assert await lis.resolve(update) is ListenOutcome.RESOLVED
    assert await task is update
    assert _registry(lis) == {}


async def test_resolve_leaves_a_peer_registration_to_its_session() -> None:
    lis = _make()
    await lis.coordinator.register_listener(ListenerKey(100, 7), PEER, replace=False)
    local = await _pending(lis, 100)
    try:
        assert await lis.resolve(make_message(100, 7, 5)) is ListenOutcome.FOREIGN
        assert not local.done()
        assert _registry(lis)[ListenerKey(100, 7)] == PEER
    finally:
        await _drain(local)


async def test_resolve_bypass_cancels_a_peer_registration() -> None:
    lis = _make(is_bypass_func=lambda update: True)
    await lis.coordinator.register_listener(ListenerKey(100, 7), PEER, replace=False)

    assert await lis.resolve(make_message(100, 7, 5)) is ListenOutcome.UNMATCHED
    assert _registry(lis) == {}


async def test_resolve_bypass_cancels_the_local_listener() -> None:
    lis = _make(is_bypass_func=lambda update: True)
    task = await _pending(lis, 100, 7)

    assert await lis.resolve(make_message(100, 7, 5)) is ListenOutcome.UNMATCHED
    with pytest.raises(ListenerCancelled):
        await task
    assert lis.listeners == {}
    assert _registry(lis) == {}


async def test_resolve_skips_an_own_registration_without_its_waiter() -> None:
    lis = _make()
    await lis.coordinator.register_listener(
        ListenerKey(100, 7, 5), lis.coordinator.new_owner_id(), replace=False
    )
    chat_wide = await _pending(lis, 100)
    update = make_message(100, 7, 5)

    assert await lis.resolve(update) is ListenOutcome.RESOLVED
    assert await chat_wide is update


async def test_resolve_tries_the_next_listener_when_the_claim_is_lost() -> None:
    class Contended(MemoryUpdateCoordinator):
        async def unregister_listener(self, key: ListenerKey, owner_id: str) -> bool:
            if key == ListenerKey(100, 7, 5):
                return False  # another update claimed it first
            return await super().unregister_listener(key, owner_id)

    lis = _make(coordinator=Contended(Message))
    exact = await _pending(lis, 100, 7, 5)
    chat_wide = await _pending(lis, 100)
    update = make_message(100, 7, 5)
    try:
        assert await lis.resolve(update) is ListenOutcome.RESOLVED
        assert await chat_wide is update
        assert not exact.done()
    finally:
        await _drain(exact)


# --- extract_key / extract_lock_key / is_bypass -------------------------------------


async def test_extract_key_requires_func_or_override() -> None:
    lis = _Listener()
    with pytest.raises(NotImplementedError, match="_Listener must either pass extract_key_func"):
        await lis.extract_key(make_message())


async def test_extract_key_rejects_the_wrong_update_type() -> None:
    with pytest.raises(TypeError):
        await _make().extract_key("not a message")  # type: ignore[arg-type]


async def test_extract_key_with_sync_and_async_funcs() -> None:
    update = make_message(100, 7, 5)
    assert await _make().extract_key(update) == ListenerKey(100, 7, 5)
    assert await _make(extract_key_func=_chat_key).extract_key(update) == ListenerKey(100)


async def test_extract_key_runs_a_sync_func_on_the_client_executor() -> None:
    executor = ThreadPoolExecutor(1, thread_name_prefix="pyroflow-extract")
    try:
        lis = _make(extract_key_func=lambda u: threading.current_thread().name)
        update = make_message(_client=SimpleNamespace(executor=executor))
        assert (await lis.extract_key(update)).startswith("pyroflow-extract")
    finally:
        executor.shutdown()


async def test_extract_lock_key_defaults_to_the_chat() -> None:
    assert await _make().extract_lock_key(ListenerKey(1, 2, 3)) == (1,)


async def test_extract_lock_key_with_sync_and_async_funcs() -> None:
    async def by_user(key: ListenerKey) -> tuple[int, int | None]:
        return (key.chat_id, key.user_id)

    key = ListenerKey(1, 2, 3)
    assert await _make(extract_lock_key_func=lambda k: (k.message_id,)).extract_lock_key(key) == (
        3,
    )
    assert await _make(extract_lock_key_func=by_user).extract_lock_key(key) == (1, 2)


async def test_is_bypass_without_func_is_false_without_validation() -> None:
    assert await _make().is_bypass("not a message") is False  # type: ignore[arg-type]


async def test_is_bypass_rejects_the_wrong_update_type_with_func() -> None:
    with pytest.raises(TypeError):
        await _make(is_bypass_func=lambda u: True).is_bypass("not a message")  # type: ignore[arg-type]


async def test_is_bypass_with_sync_and_async_funcs() -> None:
    update = make_message()
    assert await _make(is_bypass_func=lambda u: True).is_bypass(update) is True
    assert await _make(is_bypass_func=lambda u: False).is_bypass(update) is False
    assert await _make(is_bypass_func=_is_true).is_bypass(update) is True


async def test_is_bypass_runs_a_sync_func_on_the_client_executor() -> None:
    executor = ThreadPoolExecutor(1, thread_name_prefix="pyroflow-bypass")
    try:
        lis = _make(is_bypass_func=lambda u: threading.current_thread().name)
        update = make_message(_client=SimpleNamespace(executor=executor))
        assert (await lis.is_bypass(update)).startswith("pyroflow-bypass")
    finally:
        executor.shutdown()
