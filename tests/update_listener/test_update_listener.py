"""Behavioural tests for UpdateListener + MemoryListenerCoordinator.

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
from pyrogram.types import Message

from pyroflow import MessageListener
from pyroflow.enums import DuplicatePolicy
from pyroflow.errors import (
    ListenerAlreadyExists,
    ListenerCancelled,
    ListenerTimeout,
    UnresolvedUpdate,
)
from pyroflow.listener_coordinator import MemoryListenerCoordinator
from pyroflow.models import ListenerKey, ListenerModel
from pyroflow.update_listener import update_listener as update_listener_module
from pyroflow.update_listener.update_listener import UpdateListener

from ..conftest import make_message


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
    regardless of who they are" — has always been registrable. Before the
    combination-based sub_keys() it could never be reached: resolution only
    tried prefixes, so (chat, None, message) was never among the candidates
    and the listener sat there until it timed out."""
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
    listener must keep winning over a (chat, None, message) one, so the new
    rung cannot steal updates from listeners that already worked."""
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


def test_init_defaults() -> None:
    lis = _Listener()
    assert isinstance(lis.coordinator, MemoryListenerCoordinator)
    assert lis.coordinator.listener is lis
    assert lis.duplicate_policy is DuplicatePolicy.REPLACE
    assert lis.extract_key_func is None
    assert lis.is_bypass_func is None
    assert lis.timeout is None
    assert lis.listeners == {}


def test_init_stores_arguments_and_calls_factory_with_self() -> None:
    seen: list[UpdateListener] = []

    def factory(listener: UpdateListener) -> MemoryListenerCoordinator:
        seen.append(listener)
        return MemoryListenerCoordinator(listener)

    def bypass(update: Message) -> bool:
        return False

    lis = _Listener(
        coordinator_factory=factory,
        duplicate_policy=DuplicatePolicy.REJECT,
        extract_key_func=_key_of,
        is_bypass_func=bypass,
        timeout=3,
    )
    assert seen == [lis]
    assert lis.coordinator.listener is lis
    assert lis.duplicate_policy is DuplicatePolicy.REJECT
    assert lis.extract_key_func is _key_of
    assert lis.is_bypass_func is bypass
    assert lis.timeout == 3


def test_init_passes_unknown_kwargs_up_the_mro() -> None:
    with pytest.raises(TypeError):
        _Listener(unknown=1)


async def test_start_starts_the_coordinator() -> None:
    calls: list[str] = []

    class Coordinator(MemoryListenerCoordinator):
        async def start(self) -> None:
            calls.append("start")

    await _make(coordinator_factory=Coordinator).start()
    assert calls == ["start"]


async def test_stop_cancels_every_listener_and_stops_the_coordinator() -> None:
    calls: list[str] = []

    class Coordinator(MemoryListenerCoordinator):
        async def stop(self) -> None:
            calls.append("stop")
            await super().stop()

    lis = _make(coordinator_factory=Coordinator)
    first = await _pending(lis, 1)
    second = await _pending(lis, 2, 3)

    await lis.stop()

    for task in (first, second):
        with pytest.raises(ListenerCancelled):
            await task
    assert lis.listeners == {}
    assert lis.coordinator.data == {}
    assert calls == ["stop"]


async def test_stop_warns_when_listeners_remain(caplog: pytest.LogCaptureFixture) -> None:
    class Stubborn(_Listener):
        async def cancel(self, *args: Any, **kw: Any) -> bool:
            return False

    lis = Stubborn()
    key = ListenerKey(1)
    lis.listeners[key] = ListenerModel(key)

    with caplog.at_level(logging.WARNING, logger=update_listener_module.log.name):
        await lis.stop()

    assert "Stop Message UpdateListener completed with active listeners remaining" in caplog.text


async def test_stop_without_listeners_does_not_warn(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.WARNING, logger=update_listener_module.log.name):
        await _make().stop()
    assert "active listeners remaining" not in caplog.text


async def test__cancel_without_local_listener_cancels_the_coordinator() -> None:
    lis = _make()
    key = ListenerKey(1)
    await lis.coordinator.register(key)

    assert await lis._cancel(key) is True
    assert not await lis.coordinator.registered(key)


async def test__cancel_can_leave_the_coordinator_untouched() -> None:
    lis = _make()
    task = await _pending(lis, 1)
    key = ListenerKey(1)

    assert await lis._cancel(key, cancel_coordinator=False) is True
    assert key not in lis.listeners
    assert await lis.coordinator.registered(key)
    with pytest.raises(ListenerCancelled) as exc:
        await task
    assert exc.value.value == key
    assert exc.value.is_duplicate is False


async def test__cancel_marks_duplicates() -> None:
    lis = _make()
    task = await _pending(lis, 1)

    assert await lis._cancel(ListenerKey(1), is_duplicate=True) is True
    with pytest.raises(ListenerCancelled) as exc:
        await task
    assert exc.value.is_duplicate is True


async def test__cancel_with_matching_coordinator_id_cancels() -> None:
    lis = _make()
    task = await _pending(lis, 1)
    key = ListenerKey(1)
    token = lis.listeners[key].coordinator_id

    assert await lis._cancel(key, coordinator_id=token) is True
    with pytest.raises(ListenerCancelled):
        await task
    assert not await lis.coordinator.registered(key)


async def test__cancel_ignores_a_stale_coordinator_id() -> None:
    lis = _make()
    task = await _pending(lis, 1)
    key = ListenerKey(1)
    token = lis.listeners[key].coordinator_id
    try:
        assert await lis._cancel(key, coordinator_id=token + 100) is False
        assert key in lis.listeners
        assert not task.done()
        assert await lis.coordinator.registered(key, token)
    finally:
        await _drain(task)


async def test_cancel_takes_the_chat_lock() -> None:
    lis = _make()
    task = await _pending(lis, 1)
    lock = lis.coordinator.lock(
        ListenerKey(1)
    )  # strong reference: the coordinator holds locks weakly
    try:
        async with lock:
            with pytest.raises(asyncio.TimeoutError):
                await asyncio.wait_for(lis.cancel(ListenerKey(1)), 0.02)
            assert not task.done()

        assert await lis.cancel(ListenerKey(1)) is True
        with pytest.raises(ListenerCancelled):
            await task
    finally:
        await _drain(task)


async def test_cancel_forwards_its_arguments() -> None:
    lis = _make()
    task = await _pending(lis, 1)
    key = ListenerKey(1)
    token = lis.listeners[key].coordinator_id

    assert await lis.cancel(key, cancel_coordinator=False, coordinator_id=token + 1) is False
    assert await lis.cancel(key, cancel_coordinator=False, is_duplicate=True) is True
    with pytest.raises(ListenerCancelled) as exc:
        await task
    assert exc.value.is_duplicate is True


async def test__cleanup_listen_drops_only_the_listener_of_that_future() -> None:
    lis = _make()
    key = ListenerKey(1)
    current = ListenerModel(key)
    lis.listeners[key] = current

    lis._cleanup_listen(key, asyncio.get_running_loop().create_future())
    assert lis.listeners[key] is current

    lis._cleanup_listen(key, current.future)
    assert key not in lis.listeners

    lis._cleanup_listen(key, current.future)  # no listener left: a no-op
    assert lis.listeners == {}


async def test_listen_registers_locally_and_in_the_coordinator() -> None:
    lis = _make()
    task = await _pending(lis, 1, 2, 3, {"step": 1})
    key = ListenerKey(1, 2, 3)
    try:
        listener = lis.listeners[key]
        assert listener.key == key
        assert listener.meta == {"step": 1}
        assert listener.coordinator_id is not None
        assert await lis.coordinator.registered(key, listener.coordinator_id)
    finally:
        await _drain(task)


async def test_listen_unregisters_after_resolution() -> None:
    lis = _make()
    task = await _pending(lis, 100, 7, 5)
    update = make_message(100, 7, 5)
    await lis.resolve(update)

    assert await task is update
    assert lis.listeners == {}
    assert lis.coordinator.data == {}


async def test_listen_replace_keeps_the_new_registration() -> None:
    lis = _make()
    first = await _pending(lis, 1)
    old_token = lis.listeners[ListenerKey(1)].coordinator_id
    second = await _pending(lis, 1)
    try:
        with pytest.raises(ListenerCancelled) as exc:
            await first
        assert exc.value.is_duplicate is True

        new_token = lis.listeners[ListenerKey(1)].coordinator_id
        assert new_token != old_token
        # the old waiter's `unregister` must not delete the replacement
        assert await lis.coordinator.registered(ListenerKey(1), new_token)
    finally:
        await _drain(second)


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


async def test_listen_unknown_duplicate_policy_raises_type_error() -> None:
    lis = _make()
    first = await _pending(lis, 1)
    lis.duplicate_policy = "bogus"  # type: ignore[assignment]
    try:
        with pytest.raises(TypeError, match="duplicate_policy"):
            await lis.listen(1)
        assert not first.done()
    finally:
        await _drain(first)


async def test_listen_detects_local_and_coordinator_out_of_sync() -> None:
    lis = _make()
    first = await _pending(lis, 1)
    await lis.coordinator.cancel(ListenerKey(1))
    try:
        with pytest.raises(RuntimeError, match="out of sync"):
            await lis.listen(1)
    finally:
        await _drain(first)


async def test_listen_timeout_carries_the_key_and_cleans_up() -> None:
    lis = _make()
    with pytest.raises(ListenerTimeout) as exc:
        await lis.listen(1, 2, timeout=0.01)
    assert exc.value.value == ListenerKey(1, 2)
    assert exc.value.__suppress_context__ is True
    assert lis.listeners == {}
    assert lis.coordinator.data == {}


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
    assert lis.coordinator.data == {}


def test_call_is_listen() -> None:
    assert UpdateListener.__call__ is UpdateListener.listen


async def test_resolve_without_key_calls_on_unresolved_and_skips_listeners() -> None:
    calls: list[Message] = []

    class Recording(_Listener):
        async def on_unresolved(self, update: Message) -> None:
            calls.append(update)

    lis = Recording(extract_key_func=lambda update: None)
    task = await _pending(lis, 100)
    update = make_message(100, 7, 5)
    try:
        assert await lis.resolve(update) is None
        assert calls == [update]
        assert not task.done()
    finally:
        await _drain(task)


async def test_resolve_without_listeners_calls_on_unresolved() -> None:
    calls: list[Message] = []

    class Recording(_Listener):
        async def on_unresolved(self, update: Message) -> None:
            calls.append(update)

    lis = Recording(extract_key_func=_key_of)
    update = make_message(100, 7, 5)
    assert await lis.resolve(update) is None
    assert calls == [update]


async def test_resolve_without_listeners_raises_by_default() -> None:
    lis = _make(extract_key_func=_key_of)
    update = make_message()

    with pytest.raises(UnresolvedUpdate) as exc:
        await lis.resolve(update)
    assert exc.value.value is update


async def test_resolve_without_match_calls_on_unresolved() -> None:
    calls: list[Message] = []

    class Recording(_Listener):
        async def on_unresolved(self, update: Message) -> None:
            calls.append(update)

    lis = Recording(extract_key_func=_key_of)
    other = await _pending(lis, 999)
    update = make_message(100, 7, 5)
    try:
        await lis.resolve(update)
        assert calls == [update]
        assert not other.done()
    finally:
        await _drain(other)


async def test_resolve_without_match_raises_by_default() -> None:
    lis = _make()
    other = await _pending(lis, 999)
    update = make_message(100, 7, 5)
    try:
        with pytest.raises(UnresolvedUpdate) as exc:
            await lis.resolve(update)
        assert exc.value.value is update
    finally:
        await _drain(other)


async def test_resolve_discards_a_superseded_listener_and_tries_the_next() -> None:
    lis = _make()
    exact = await _pending(lis, 100, 7, 5)
    chat_wide = await _pending(lis, 100)
    key = ListenerKey(100, 7, 5)

    # another session took the key over; its cancel signal has not arrived yet
    await lis.coordinator.cancel(key)
    foreign = await lis.coordinator.register(key)

    update = make_message(100, 7, 5)
    await lis.resolve(update)

    with pytest.raises(ListenerCancelled):
        await exact
    assert await chat_wide is update
    assert await lis.coordinator.registered(key, foreign)


async def test_resolve_with_only_a_superseded_listener_is_unresolved() -> None:
    lis = _make()
    exact = await _pending(lis, 100, 7, 5)
    key = ListenerKey(100, 7, 5)
    await lis.coordinator.cancel(key)
    foreign = await lis.coordinator.register(key)

    with pytest.raises(UnresolvedUpdate):
        await lis.resolve(make_message(100, 7, 5))
    with pytest.raises(ListenerCancelled):
        await exact
    assert await lis.coordinator.registered(key, foreign)


async def test_resolve_bypass_cancels_the_listener_and_calls_on_unresolved() -> None:
    lis = _make(is_bypass_func=lambda update: True)
    task = await _pending(lis, 100, 7)
    update = make_message(100, 7, 5)

    with pytest.raises(UnresolvedUpdate) as exc:
        await lis.resolve(update)
    assert exc.value.value is update
    with pytest.raises(ListenerCancelled):
        await task
    assert lis.listeners == {}
    assert lis.coordinator.data == {}


async def test_on_unresolved_raises_unresolved_update() -> None:
    update = make_message()
    with pytest.raises(UnresolvedUpdate) as exc:
        await _make().on_unresolved(update)
    assert exc.value.value is update


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
