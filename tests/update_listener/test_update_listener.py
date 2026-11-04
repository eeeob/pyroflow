"""Behavioural tests for UpdateListener.

Covers key matching and the default timeout using the real MessageListener,
then every UpdateListener element directly through a minimal local subclass.
"""

from __future__ import annotations as _annotations

import asyncio
import threading
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
from typing import Any

import pytest
from pyrogram.types import Message

from pyroflow import MessageListener
from pyroflow.enums import DuplicatePolicy
from pyroflow.errors import ListenerAlreadyExists, ListenerCancelled, ListenerTimeout
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


def test_module_exports() -> None:
    assert update_listener_module.__all__ == ("UpdateListener",)


# --- __init__ -----------------------------------------------------------------


def test_init_defaults() -> None:
    lis = _Listener()
    assert lis.duplicate_policy is DuplicatePolicy.REPLACE
    assert lis.extract_key_func is None
    assert lis.is_bypass_func is None
    assert lis.timeout is None
    assert lis.listeners == {}
    assert lis.is_closed is False


def test_init_stores_arguments() -> None:
    def bypass(update: Message) -> bool:
        return False

    lis = _Listener(
        duplicate_policy=DuplicatePolicy.REJECT,
        extract_key_func=_key_of,
        is_bypass_func=bypass,
        timeout=3,
    )
    assert lis.duplicate_policy is DuplicatePolicy.REJECT
    assert lis.extract_key_func is _key_of
    assert lis.is_bypass_func is bypass
    assert lis.timeout == 3


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


# --- cancel -------------------------------------------------------------------


async def test_cancel_fails_the_waiter_and_removes_it() -> None:
    lis = _make()
    task = await _pending(lis, 1)
    key = ListenerKey(1)

    assert lis.cancel(key) is True
    assert key not in lis.listeners
    with pytest.raises(ListenerCancelled) as exc:
        await task
    assert exc.value.value == key
    assert exc.value.is_duplicate is False


async def test_cancel_marks_duplicates() -> None:
    lis = _make()
    task = await _pending(lis, 1)

    assert lis.cancel(ListenerKey(1), is_duplicate=True) is True
    with pytest.raises(ListenerCancelled) as exc:
        await task
    assert exc.value.is_duplicate is True


async def test_cancel_without_a_listener_is_false_and_leaves_a_finished_one_as_is() -> None:
    lis = _make()
    lis.listeners[ListenerKey(2)] = done = ListenerModel(ListenerKey(2))
    done.resolve("update")

    assert lis.cancel(ListenerKey(1)) is False
    assert lis.cancel(ListenerKey(2)) is True
    assert await done.future == "update"


# --- listen ---------------------------------------------------------------------


async def test_listen_registers_the_listener_before_yielding() -> None:
    lis = _make()
    coro = lis.listen(1, 2, 3, {"step": 1}, prompt_id=9)
    task = asyncio.ensure_future(coro)
    # One loop turn starts the coroutine; it registers before it first waits.
    await asyncio.sleep(0)
    key = ListenerKey(1, 2, 3)
    try:
        listener = lis.listeners[key]
        assert listener.key == key
        assert listener.meta == {"step": 1}
        assert listener.prompt_id == 9
    finally:
        await _drain(task)


async def test_listen_replace_cancels_the_old_listener_and_keeps_the_new() -> None:
    lis = _make()
    first = await _pending(lis, 1)
    second = await _pending(lis, 1)
    try:
        with pytest.raises(ListenerCancelled) as exc:
            await first
        assert exc.value.is_duplicate is True
        # the old waiter's cleanup must not drop the replacement
        assert ListenerKey(1) in lis.listeners
        assert not second.done()
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


async def test_listen_timeout_carries_the_key_and_cleans_up() -> None:
    lis = _make()
    with pytest.raises(ListenerTimeout) as exc:
        await lis.listen(1, 2, timeout=0.01)
    assert exc.value.value == ListenerKey(1, 2)
    assert exc.value.__suppress_context__ is True
    assert lis.listeners == {}


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


def test_call_is_listen() -> None:
    assert UpdateListener.__call__ is UpdateListener.listen


# --- resolve ----------------------------------------------------------------------


async def test_resolve_without_key_is_false_and_skips_listeners() -> None:
    lis = _make(extract_key_func=lambda update: None)
    task = await _pending(lis, 100)
    try:
        assert await lis.resolve(make_message(100, 7, 5)) is False
        assert not task.done()
    finally:
        await _drain(task)


async def test_resolve_without_a_matching_listener_is_false() -> None:
    lis = _make()
    other = await _pending(lis, 999)
    try:
        assert await lis.resolve(make_message(100, 7, 5)) is False
        assert not other.done()
    finally:
        await _drain(other)


async def test_resolve_hands_the_update_to_its_listener_and_removes_it() -> None:
    lis = _make()
    task = await _pending(lis, 100, 7)
    update = make_message(100, 7, 5)

    assert await lis.resolve(update) is True
    assert lis.listeners == {}
    assert await task is update


async def test_resolve_skips_a_finished_listener() -> None:
    lis = _make()
    lis.listeners[ListenerKey(100, 7, 5)] = finished = ListenerModel(ListenerKey(100, 7, 5))
    finished.resolve("earlier")
    chat_wide = await _pending(lis, 100)
    update = make_message(100, 7, 5)

    assert await lis.resolve(update) is True
    assert await chat_wide is update


async def test_resolve_bypass_cancels_the_listener_and_is_false() -> None:
    lis = _make(is_bypass_func=lambda update: True)
    task = await _pending(lis, 100, 7)

    assert await lis.resolve(make_message(100, 7, 5)) is False
    with pytest.raises(ListenerCancelled):
        await task
    assert lis.listeners == {}


async def test_resolve_skips_a_listener_taken_while_is_bypass_ran() -> None:
    async def slow_no_bypass(update: Message) -> bool:
        await asyncio.sleep(0.01)
        return False

    lis = _make(is_bypass_func=slow_no_bypass)
    task = await _pending(lis, 100, 7)
    first, second = make_message(100, 7, 5), make_message(100, 7, 6)

    results = await asyncio.gather(lis.resolve(first), lis.resolve(second))

    assert results == [True, False]
    assert await task is first
    assert lis.listeners == {}


# --- extract_key / is_bypass ----------------------------------------------------


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
