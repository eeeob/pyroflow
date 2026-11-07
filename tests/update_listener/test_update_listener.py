"""Behavioural tests for UpdateListener.

Covers key matching and the default timeout using the real MessageListener,
then every UpdateListener element directly through a minimal local subclass.
"""

from __future__ import annotations as _annotations

import asyncio
import dataclasses
import gc
import inspect
import logging
import threading
import weakref
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
from typing import Any

import pytest
from pyrogram import filters
from pyrogram.types import Message

from pyroflow import MessageListener
from pyroflow.dispatcher import _HANDLER_WORKER
from pyroflow.enums import DuplicatePolicy, ListenerScope
from pyroflow.errors import (
    ListenerAlreadyExists,
    ListenerCancelled,
    ListenerEvicted,
    ListenerRejected,
    ListenerReplaced,
    ListenerTimeout,
    ListenerWorkersBusy,
)
from pyroflow.models import CallbackQueryKey, ListenerContext, ListenerModel, MessageKey
from pyroflow.update_listener import update_listener as update_listener_module
from pyroflow.update_listener.update_listener import UpdateListener


from ..conftest import make_message


CHAT = 0b00001
"""Shape bit of `MessageKey.chat_id`."""
USER = 0b00010
"""Shape bit of `MessageKey.user_id`."""
TOPIC = 0b00100
"""Shape bit of `MessageKey.message_thread_id`."""


async def _started(listener: MessageListener) -> MessageListener:
    await listener.start()
    return listener


async def test_resolve_matches_less_specific_key() -> None:
    """A chat-only wait takes an update that carries a user too."""
    lis = await _started(MessageListener())
    try:
        task = asyncio.ensure_future(lis.listen(chat_id=100))
        await asyncio.sleep(0.02)
        await lis.resolve(make_message(100, 7, 5))
        got = await asyncio.wait_for(task, 1)
        assert got.chat.id == 100
    finally:
        await lis.stop()


async def test_resolve_matches_a_topic_wait_without_a_user() -> None:
    """`listen(chat_id=..., message_thread_id=...)` takes whoever answers in that topic."""
    lis = await _started(MessageListener())
    try:
        task = asyncio.ensure_future(lis.listen(chat_id=100, message_thread_id=3, timeout=5))
        await asyncio.sleep(0.02)

        await lis.resolve(make_message(100, 7, 5, message_thread_id=3))

        got = await asyncio.wait_for(task, 1)
        assert got.id == 5
    finally:
        await lis.stop()


async def test_user_listener_outranks_a_topic_one() -> None:
    """Ordering is by number of fields, then by field order: a (chat, user)
    wait wins over a (chat, topic) one."""
    lis = await _started(MessageListener())
    try:
        by_user = asyncio.ensure_future(lis.listen(chat_id=100, user_id=7, timeout=5))
        by_topic = asyncio.ensure_future(lis.listen(chat_id=100, message_thread_id=3, timeout=5))
        await asyncio.sleep(0.02)

        await lis.resolve(make_message(100, 7, 5, message_thread_id=3))

        got = await asyncio.wait_for(by_user, 1)
        assert got.id == 5
        assert not by_topic.done(), "the lower priority listener was consumed"
    finally:
        by_topic.cancel()
        await asyncio.gather(by_topic, return_exceptions=True)
        await lis.stop()


async def test_listener_default_timeout_used_when_not_overridden() -> None:
    lis = await _started(MessageListener(timeout=0.05))
    try:
        with pytest.raises(ListenerTimeout):
            await lis.listen(chat_id=300, user_id=7)  # no per-call timeout → falls back to 0.05
    finally:
        await lis.stop()


# --- UpdateListener base: a local subclass exercises every hook directly ---


class _Listener(UpdateListener[Message, MessageKey]):
    __update_type__ = Message
    __key_type__ = MessageKey


def _key_of(update: Message) -> MessageKey:
    return MessageKey(update.chat.id, update.from_user.id, update.message_thread_id)


def _make(**kw: Any) -> _Listener:
    kw.setdefault("extract_key_func", _key_of)
    return _Listener(**kw)


async def _pending(lis: UpdateListener, key: MessageKey, **kw: Any) -> asyncio.Task:
    task = asyncio.ensure_future(lis.listen(key, **kw))
    await asyncio.sleep(0.01)
    return task


async def _drain(*tasks: asyncio.Future) -> None:
    for task in tasks:
        task.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)


def _model(key: MessageKey) -> ListenerModel:
    return ListenerModel(key, asyncio.get_running_loop().create_future())


def _never(_: object, __: object, update: Message) -> bool:
    return False


async def _starts_with_a(_: object, __: object, update: Message) -> bool:
    return (update.text or "").startswith("a")


TEXT_A = filters.create(_starts_with_a)
"""Filter: text starting with `a`."""


def _chat_key(update: Message) -> MessageKey:
    return MessageKey(update.chat.id)


def test_module_exports() -> None:
    assert update_listener_module.__all__ == ("ListenKw", "UpdateListener")


def test_listen_kw_holds_the_optional_arguments_of_a_wait() -> None:
    listen_kw = update_listener_module.ListenKw

    assert listen_kw.__required_keys__ == frozenset()
    assert list(listen_kw.__annotations__) == ["context", "filters", "strict", "timeout"]


def test_module_logger() -> None:
    assert update_listener_module.log.name == "pyroflow.update_listener.update_listener"


def test_update_listener_is_generic_over_update_and_key_type() -> None:
    assert UpdateListener.__parameters__ == (
        update_listener_module.UpdateType,
        update_listener_module.KeyT,
    )


# --- __init__ -----------------------------------------------------------------


def test_init_defaults() -> None:
    lis = _Listener()
    assert lis.duplicate_policy is DuplicatePolicy.REPLACE
    assert lis.extract_key_func is None
    assert lis.on_error_func is None
    assert lis.timeout is None
    assert lis.resolve_scope is ListenerScope.FIRST
    assert lis.strict_filter is None
    assert lis.listeners == {}
    assert lis.is_closed is False
    assert lis._shapes == {}
    assert lis._shape_order == ()


def test_init_stores_arguments() -> None:
    lis = _Listener(
        duplicate_policy=DuplicatePolicy.REJECT,
        extract_key_func=_key_of,
        on_error_func=print,
        timeout=3,
        resolve_scope=ListenerScope.ALL,
        strict_filter=TEXT_A,
    )
    assert lis.duplicate_policy is DuplicatePolicy.REJECT
    assert lis.extract_key_func is _key_of
    assert lis.on_error_func is print
    assert lis.timeout == 3
    assert lis.resolve_scope is ListenerScope.ALL
    assert lis.strict_filter is TEXT_A


def test_init_computes_the_exact_mask_of_the_key_type() -> None:
    assert _Listener()._exact_mask == 0b10000


def test_init_passes_unknown_kwargs_up_the_mro() -> None:
    with pytest.raises(TypeError):
        _Listener(unknown=1)


# --- start / stop -------------------------------------------------------------


async def test_stop_cancels_every_listener_and_refuses_listen_until_start() -> None:
    lis = _make()
    first = await _pending(lis, MessageKey(1))
    second = await _pending(lis, MessageKey(2, 3))

    await lis.stop()

    for task in (first, second):
        with pytest.raises(ListenerCancelled):
            await task
    assert lis.listeners == {}
    assert lis._shapes == {}
    assert lis._shape_order == ()
    assert lis.is_closed is True
    with pytest.raises(ListenerCancelled):
        await lis.listen(MessageKey(1))

    await lis.start()

    assert lis.is_closed is False
    with pytest.raises(ListenerTimeout):
        await lis.listen(MessageKey(1), timeout=0.01)


# --- shapes -------------------------------------------------------------------


def test_shape_of_sets_a_bit_per_field_set_but_not_the_exact_ones() -> None:
    lis = _Listener()
    assert lis._shape_of(MessageKey().to_tuple()) == 0
    assert lis._shape_of(MessageKey(1, 2).to_tuple()) == CHAT | USER
    assert lis._shape_of(MessageKey(1, None, 3).to_tuple()) == CHAT | TOPIC
    assert lis._shape_of(MessageKey(1, 2, ephemeral=True).to_tuple()) == CHAT | USER


async def test_order_shapes_puts_more_fields_first_then_field_order() -> None:
    lis = _Listener()
    for key in (
        MessageKey(1),
        MessageKey(1, None, 3),
        MessageKey(),
        MessageKey(1, 2),
    ):
        lis._add(_model(key))

    assert lis._shape_order == (CHAT | USER, CHAT | TOPIC, CHAT, 0)


async def test_add_counts_each_shape_and_orders_a_new_one() -> None:
    lis = _Listener()
    lis._add(_model(MessageKey(1)))
    lis._add(_model(MessageKey(2)))
    lis._add(_model(MessageKey(1, 2)))

    assert lis._shapes == {CHAT: 2, CHAT | USER: 1}
    assert lis._shape_order == (CHAT | USER, CHAT)


async def test_add_in_place_of_a_model_on_the_same_key_keeps_the_count() -> None:
    lis = _Listener()
    old, new = _model(MessageKey(1)), _model(MessageKey(1))
    lis._add(old)
    lis._add(new)

    assert lis.listeners == {MessageKey(1): new}
    assert lis._shapes == {CHAT: 1}


async def test_remove_uncounts_the_shape_and_drops_a_shape_left_empty() -> None:
    lis = _Listener()
    model = _model(MessageKey(1))
    lis._add(model)
    lis._add(_model(MessageKey(2)))
    lis._add(_model(MessageKey(1, 2)))

    assert lis._remove(MessageKey(1)) is model
    assert lis._shapes == {CHAT: 1, CHAT | USER: 1}

    lis._remove(MessageKey(1, 2))
    assert lis._shapes == {CHAT: 1}
    assert lis._shape_order == (CHAT,)


async def test_remove_of_a_missing_key_is_none() -> None:
    lis = _Listener()
    lis._add(_model(MessageKey(1)))

    assert lis._remove(MessageKey(2)) is None
    assert lis._shapes == {CHAT: 1}


@pytest.mark.parametrize(
    "end",
    [
        lambda lis, key: lis.cancel(key),
        lambda lis, key: lis.reject(key),
        lambda lis, key: lis.evict(key),
    ],
)
async def test_ending_a_wait_uncounts_its_shape(end: Any) -> None:
    lis = _make()
    task = await _pending(lis, MessageKey(1, 2))
    assert lis._shapes == {CHAT | USER: 1}

    end(lis, MessageKey(1, 2))
    await _drain(task)

    assert lis._shapes == {}
    assert lis._shape_order == ()


async def test_a_wait_that_takes_its_update_or_times_out_uncounts_its_shape() -> None:
    lis = _make()
    task = await _pending(lis, MessageKey(1, 2))
    await lis.resolve(make_message(1, 2))
    await task

    with pytest.raises(ListenerTimeout):
        await lis.listen(MessageKey(1), timeout=0.01)

    assert lis._shapes == {}
    assert lis._shape_order == ()


async def test_replacing_a_wait_keeps_one_count_for_its_shape() -> None:
    lis = _make()
    first = await _pending(lis, MessageKey(1))
    second = await _pending(lis, MessageKey(1))
    try:
        assert lis._shapes == {CHAT: 1}
    finally:
        await _drain(first, second)

    assert lis._shapes == {}


# --- cancel / reject -----------------------------------------------------------


async def test_cancel_fails_the_waiter_and_removes_it() -> None:
    lis = _make()
    task = await _pending(lis, MessageKey(1))
    key = MessageKey(1)

    assert lis.cancel(key) is True
    assert key not in lis.listeners
    with pytest.raises(ListenerCancelled) as exc:
        await task
    assert exc.value.value == key
    assert not isinstance(exc.value, ListenerReplaced)


async def test_cancel_without_a_listener_is_false_and_leaves_a_finished_one_as_is() -> None:
    lis = _make()
    lis._add(done := _model(MessageKey(2)))
    done.resolve("update")

    assert lis.cancel(MessageKey(1)) is False
    assert lis.cancel(MessageKey(2)) is True
    assert await done.future == "update"


async def test_reject_fails_the_waiter_and_removes_it() -> None:
    lis = _make()
    task = await _pending(lis, MessageKey(1))

    assert lis.reject(MessageKey(1)) is True
    assert MessageKey(1) not in lis.listeners
    with pytest.raises(ListenerRejected):
        await task


async def test_reject_without_a_listener_is_false_and_leaves_a_finished_one_as_is() -> None:
    lis = _make()
    lis._add(done := _model(MessageKey(2)))
    done.resolve("update")

    assert lis.reject(MessageKey(1)) is False
    assert lis.reject(MessageKey(2)) is True
    assert await done.future == "update"


async def test_evict_fails_the_waiter_with_listener_evicted_and_removes_it() -> None:
    lis = _make()
    task = await _pending(lis, MessageKey(100))
    model = lis.listeners[MessageKey(100)]

    assert lis.evict(MessageKey(100), model=model) is True
    with pytest.raises(ListenerEvicted):
        await task
    assert lis.listeners == {}


async def test_evict_spares_a_newer_wait_and_a_missing_key() -> None:
    lis = _make()
    task = await _pending(lis, MessageKey(100))
    try:
        assert lis.evict(MessageKey(100), model=_model(MessageKey(100))) is False
        assert lis.evict(MessageKey(999)) is False
        assert not task.done()
    finally:
        await _drain(task)


# --- listen ---------------------------------------------------------------------


class _Holder:
    """Stands in for the dispatcher of a worker: records what `listen` does with it."""

    def __init__(
        self,
        error: Exception | None = None,
        *,
        has_policy: bool = True,
    ) -> None:
        self.error = error
        self.workers_policy = object() if has_policy else None
        self.handler_waits: dict[ListenerModel, object] = {}
        self.entered: list[MessageKey] = []
        self.ended: list[tuple[object, ListenerModel]] = []

    def enter_handler_wait(self, policy: object, key: MessageKey) -> None:
        if self.error is not None:
            raise self.error
        self.entered.append(key)

    def end_handler_wait(self, model: ListenerModel) -> None:
        if (listener := self.handler_waits.pop(model, None)) is not None:
            self.ended.append((listener, model))


def _as_worker(holder: _Holder) -> object:
    """Mark the running task as a worker of `holder`, as `Dispatcher.handler_worker` does."""
    return _HANDLER_WORKER.set((holder, asyncio.current_task()))


async def _pending_on_a_worker(lis: _Listener, holder: _Holder, chat_id: int) -> asyncio.Task:
    """Start a wait in a task that is a worker of `holder`, and let it register."""

    async def wait() -> object:
        _as_worker(holder)
        return await lis.listen(MessageKey(chat_id))

    task = asyncio.ensure_future(wait())
    await asyncio.sleep(0)
    return task


async def test_listen_waits_on_a_key_of_its_chat() -> None:
    lis = _make()
    task = asyncio.ensure_future(lis.listen(MessageKey(1), filters=TEXT_A, strict=True))
    await asyncio.sleep(0)
    try:
        assert list(lis.listeners) == [MessageKey(1)]
        assert lis.listeners[MessageKey(1)].filters is TEXT_A
    finally:
        await _drain(task)


async def test_listen_refuses_a_key_of_another_type() -> None:
    lis = _make()

    with pytest.raises(
        TypeError, match="_Listener.listen needs exactly a MessageKey, not CallbackQueryKey"
    ):
        await lis.listen(CallbackQueryKey(1))  # ty: ignore[invalid-argument-type]

    assert lis.listeners == {}


async def test_listen_refuses_a_subclass_key_its_lookups_never_match() -> None:
    lis = _make()

    with pytest.raises(TypeError, match="needs exactly a MessageKey, not _LanguageKey"):
        await lis.listen(_LanguageKey(1))

    assert lis.listeners == {}


async def test_listen_without_a_chat_takes_any_update() -> None:
    lis = _make()
    task = asyncio.ensure_future(lis.listen(MessageKey()))
    await asyncio.sleep(0)
    update = make_message(100, 7, 5)

    assert await lis.resolve(update) is True
    assert await task is update


async def test_listen_in_a_worker_task_tracks_the_wait_until_it_ends() -> None:
    holder = _Holder()
    token = _as_worker(holder)
    try:
        lis = _make()
        with pytest.raises(ListenerTimeout):
            await lis.listen(MessageKey(100), timeout=0.01)
    finally:
        _HANDLER_WORKER.reset(token)

    assert holder.entered == [MessageKey(100)]
    ((listener, model),) = holder.ended
    assert listener is lis
    assert model.key == MessageKey(100)
    assert holder.handler_waits == {}


async def test_listen_in_a_task_the_handler_spawned_is_not_counted() -> None:
    holder = _Holder()
    token = _as_worker(holder)
    try:
        lis = _make()
        with pytest.raises(ListenerTimeout):
            await asyncio.create_task(lis.listen(MessageKey(100), timeout=0.01))
    finally:
        _HANDLER_WORKER.reset(token)

    assert holder.entered == []


async def test_listen_without_a_policy_leaves_the_dispatcher_alone() -> None:
    holder = _Holder(has_policy=False)
    token = _as_worker(holder)
    try:
        with pytest.raises(ListenerTimeout):
            await _make().listen(MessageKey(100), timeout=0.01)
    finally:
        _HANDLER_WORKER.reset(token)

    assert holder.entered == []
    assert holder.ended == []


async def test_listen_refused_by_the_policy_registers_nothing() -> None:
    token = _as_worker(_Holder(error=ListenerWorkersBusy(MessageKey(100))))
    try:
        lis = _make()
        with pytest.raises(ListenerWorkersBusy):
            await lis.listen(MessageKey(100))
    finally:
        _HANDLER_WORKER.reset(token)

    assert lis.listeners == {}
    assert lis._shapes == {}


async def test_listen_refuses_a_duplicate_before_making_room_for_it() -> None:
    lis = _make(duplicate_policy=DuplicatePolicy.REJECT)
    first = await _pending(lis, MessageKey(100))
    holder = _Holder()
    token = _as_worker(holder)
    try:
        with pytest.raises(ListenerAlreadyExists):
            await lis.listen(MessageKey(100))
    finally:
        _HANDLER_WORKER.reset(token)
        await _drain(first)

    assert holder.entered == []
    assert holder.handler_waits == {}
    assert holder.ended == []


async def test_listen_replacing_a_wait_that_holds_a_slot_skips_the_check() -> None:
    lis = _make()
    holder = _Holder()
    first = await _pending_on_a_worker(lis, holder, 100)
    token = _as_worker(holder)
    try:
        with pytest.raises(ListenerTimeout):
            await lis.listen(MessageKey(100), timeout=0.01)
    finally:
        _HANDLER_WORKER.reset(token)
        await _drain(first)

    assert holder.entered == [MessageKey(100)]  # the old wait's, and no other
    assert len(holder.ended) == 2


async def test_listen_refused_while_replacing_leaves_the_old_wait_open() -> None:
    lis = _make()
    first = await _pending(lis, MessageKey(100))
    token = _as_worker(_Holder(error=ListenerWorkersBusy(MessageKey(100))))
    try:
        with pytest.raises(ListenerWorkersBusy):
            await lis.listen(MessageKey(100))
    finally:
        _HANDLER_WORKER.reset(token)

    assert not lis.listeners[MessageKey(100)].done()

    await _drain(first)


async def test_listen_replacing_a_wait_outside_a_handler_registers_without_yielding() -> None:
    lis = _make()
    first = await _pending(lis, MessageKey(100))
    second = asyncio.ensure_future(lis.listen(MessageKey(100)))
    await asyncio.sleep(0)

    assert not lis.listeners[MessageKey(100)].done()

    await _drain(first, second)


async def test_listen_replacing_a_wait_that_holds_no_worker_makes_room() -> None:
    lis = _make()
    first = await _pending(lis, MessageKey(100))
    holder = _Holder()
    token = _as_worker(holder)
    try:
        with pytest.raises(ListenerTimeout):
            await lis.listen(MessageKey(100), timeout=0.01)
    finally:
        _HANDLER_WORKER.reset(token)
        await _drain(first)

    assert holder.entered == [MessageKey(100)]


async def test_listen_on_a_worker_frees_the_slot_the_moment_the_wait_ends() -> None:
    lis = _make()
    holder = _Holder()
    task = await _pending_on_a_worker(lis, holder, 100)

    lis.cancel(MessageKey(100))

    assert len(holder.ended) == 1  # before `listen` resumes
    assert not task.done()

    await _drain(task)

    assert len(holder.ended) == 1


async def test_listen_outside_a_worker_adds_only_the_cleanup_callback() -> None:
    lis = _make()
    task = await _pending(lis, MessageKey(100))
    try:
        assert lis.listeners[MessageKey(100)].done_callbacks == [lis._cleanup_model]
    finally:
        await _drain(task)


async def test_listen_on_a_worker_with_its_task_cancelled_frees_the_slot() -> None:
    lis = _make()
    holder = _Holder()
    task = await _pending_on_a_worker(lis, holder, 100)

    task.cancel()

    with pytest.raises(asyncio.CancelledError):
        await task

    assert len(holder.ended) == 1


async def test_cleanup_model_removes_the_model() -> None:
    lis = _make()
    model = _model(MessageKey(1))
    lis._add(model)

    lis._cleanup_model(model)

    assert lis.listeners == {}
    assert lis._shapes == {}


async def test_cleanup_model_leaves_a_newer_model_on_the_key() -> None:
    lis = _make()
    old = _model(MessageKey(1))
    newer = _model(MessageKey(1))
    lis._add(newer)

    lis._cleanup_model(old)

    assert lis.listeners == {newer.key: newer}
    assert lis._shapes == {CHAT: 1}


async def test_time_out_ends_a_pending_wait() -> None:
    lis = _make()
    model = _model(MessageKey(1))

    lis._time_out(model)

    assert isinstance(model.future.exception(), ListenerTimeout)


async def test_time_out_leaves_a_finished_wait_alone() -> None:
    lis = _make()
    model = _model(MessageKey(1))
    model.resolve("update")

    lis._time_out(model)

    assert model.future.result() == "update"


async def test_listen_timeout_due_in_the_iteration_the_wait_ended_changes_nothing() -> None:
    lis = _make()
    loop = asyncio.get_running_loop()
    errors: list[object] = []
    loop.set_exception_handler(lambda _, context: errors.append(context))
    try:
        task = asyncio.ensure_future(lis.listen(MessageKey(100), timeout=0))
        await asyncio.sleep(0)

        # Due before the timer, so it runs first, with the timer in the same loop iteration.
        loop.call_at(loop.time() - 1, lis.cancel, MessageKey(100))

        with pytest.raises(ListenerCancelled):
            await task
    finally:
        loop.set_exception_handler(None)

    assert errors == []


async def test_listen_without_context_attaches_none() -> None:
    lis = _make()
    task = await _pending(lis, MessageKey(1))
    try:
        assert lis.listeners[MessageKey(1)].context is None
    finally:
        await _drain(task)


@pytest.mark.parametrize("end", ["timeout", "cancel"])
async def test_listen_leaves_no_reference_cycle_once_the_wait_fails(end: str) -> None:
    # Without the cyclic GC, the wait's future must die with the error that ended it.
    lis = _make()
    gc.disable()
    try:
        # Well past the sleep of `_pending`, which a coarse clock can stretch.
        task = await _pending(lis, MessageKey(1), timeout=0.2 if end == "timeout" else None)
        future = weakref.ref(lis.listeners[MessageKey(1)].future)

        if end == "cancel":
            lis.cancel(MessageKey(1))

        with pytest.raises(ListenerTimeout if end == "timeout" else ListenerCancelled):
            await task

        del task
        assert future() is None
    finally:
        gc.enable()


async def test_listen_registers_the_listener_before_yielding() -> None:
    lis = _make()
    context = ListenerContext(step=1)
    coro = lis.listen(MessageKey(1), context=context)
    task = asyncio.ensure_future(coro)
    # One loop turn starts the coroutine; it registers before it first waits.
    await asyncio.sleep(0)
    key = MessageKey(1)
    try:
        listener = lis.listeners[key]
        assert listener.key == key
        assert listener.context is context
    finally:
        await _drain(task)


async def test_listen_replace_cancels_the_old_listener_and_keeps_the_new() -> None:
    lis = _make()
    first = await _pending(lis, MessageKey(1))
    second = await _pending(lis, MessageKey(1))
    try:
        with pytest.raises(ListenerReplaced):
            await first
        # the old waiter's cleanup must not drop the replacement
        assert MessageKey(1) in lis.listeners
        assert not second.done()
    finally:
        await _drain(second)


async def test_listen_reject_leaves_the_first_listener_running() -> None:
    lis = _make(duplicate_policy=DuplicatePolicy.REJECT)
    first = await _pending(lis, MessageKey(1))
    try:
        with pytest.raises(ListenerAlreadyExists) as exc:
            await lis.listen(MessageKey(1))
        assert exc.value.value == MessageKey(1)
        assert not first.done()
        assert MessageKey(1) in lis.listeners
    finally:
        await _drain(first)


async def test_listen_reject_ignores_a_finished_listener_still_returning() -> None:
    lis = _make(duplicate_policy=DuplicatePolicy.REJECT)
    lis._add(finished := _model(MessageKey(1)))
    finished.resolve("update")

    task = await _pending(lis, MessageKey(1))
    try:
        assert lis.listeners[MessageKey(1)] is not finished
        assert lis._shapes == {CHAT: 1}
        assert not task.done()
    finally:
        await _drain(task)


async def test_listen_timeout_carries_the_key_and_cleans_up() -> None:
    lis = _make()
    with pytest.raises(ListenerTimeout) as exc:
        await lis.listen(MessageKey(1, 2), timeout=0.01)
    assert exc.value.value == MessageKey(1, 2)
    assert exc.value.__context__ is None
    assert lis.listeners == {}


async def test_listen_per_call_timeout_overrides_the_default() -> None:
    lis = _make(timeout=10)
    with pytest.raises(ListenerTimeout):
        await asyncio.wait_for(lis.listen(MessageKey(1), timeout=0.01), 1)


async def test_listen_external_cancellation_propagates_and_cleans_up() -> None:
    lis = _make()
    task = await _pending(lis, MessageKey(1))
    future = lis.listeners[MessageKey(1)].future

    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert future.done()
    assert lis.listeners == {}
    assert lis._shapes == {}


async def test_listen_stores_the_filter_and_strict_on_the_model() -> None:
    lis = _make()
    task = await _pending(lis, MessageKey(1), filters=TEXT_A, strict=True)
    try:
        listener = lis.listeners[MessageKey(1)]
        assert listener.filters is TEXT_A
        assert listener.strict is True
    finally:
        await _drain(task)


async def test_listen_without_filters_falls_back_to_strict_filter() -> None:
    lis = _make(strict_filter=TEXT_A)
    task = await _pending(lis, MessageKey(1))
    try:
        listener = lis.listeners[MessageKey(1)]
        assert listener.filters is TEXT_A
        assert listener.strict is True
    finally:
        await _drain(task)


async def test_listen_filters_win_over_strict_filter() -> None:
    other = filters.create(_never)
    lis = _make(strict_filter=TEXT_A)
    task = await _pending(lis, MessageKey(1), filters=other)
    try:
        listener = lis.listeners[MessageKey(1)]
        assert listener.filters is other
        assert listener.strict is False
    finally:
        await _drain(task)


@pytest.mark.parametrize(
    ("end", "error"),
    [
        (lambda lis, key: None, ListenerTimeout),
        (lambda lis, key: lis.cancel(key), ListenerCancelled),
        (lambda lis, key: lis.reject(key), ListenerRejected),
    ],
)
async def test_listen_reports_the_error_that_ended_the_wait(
    end: Any, error: type[Exception]
) -> None:
    seen: list[tuple[object, object]] = []
    lis = _make(on_error_func=lambda exc, model: seen.append((exc, model)))
    task = await _pending(lis, MessageKey(1), timeout=0.05)
    model = lis.listeners[MessageKey(1)]

    end(lis, MessageKey(1))
    with pytest.raises(error) as exc:
        await task

    assert seen == [(exc.value, model)]


async def test_listen_reports_to_an_async_func_after_removing_the_wait() -> None:
    seen: list[bool] = []
    lis = _make()

    async def record(exc: object, model: object) -> None:
        seen.append(MessageKey(1) in lis.listeners)

    lis.on_error_func = record
    with pytest.raises(ListenerTimeout):
        await lis.listen(MessageKey(1), timeout=0.01)

    assert seen == [False]


async def test_listen_logs_a_failing_on_error_func_and_raises_the_error(
    caplog: pytest.LogCaptureFixture,
) -> None:
    def boom(exc: object, model: object) -> None:
        msg = "boom"
        raise RuntimeError(msg)

    with caplog.at_level(logging.ERROR), pytest.raises(ListenerTimeout):
        await _make(on_error_func=boom).listen(MessageKey(1), timeout=0.01)
    assert "boom" in caplog.text


async def test_listen_does_not_report_an_error_raised_before_the_wait() -> None:
    seen: list[object] = []
    lis = _make(
        duplicate_policy=DuplicatePolicy.REJECT, on_error_func=lambda exc, m: seen.append(exc)
    )
    first = await _pending(lis, MessageKey(1))
    try:
        with pytest.raises(ListenerAlreadyExists):
            await lis.listen(MessageKey(1))
        assert seen == []
    finally:
        await _drain(first)


def test_call_is_listen() -> None:
    assert UpdateListener.__call__ is UpdateListener.listen


# --- resolve ----------------------------------------------------------------------


async def test_resolve_with_no_waits_skips_extracting_the_key() -> None:
    calls: list[Message] = []
    lis = _make(extract_key_func=calls.append)

    assert await lis.resolve(make_message(100, 7, 5)) is False
    assert calls == []


async def test_resolve_with_no_waits_still_rejects_the_wrong_update_type() -> None:
    with pytest.raises(TypeError):
        await _make().resolve("not a message")  # ty: ignore[invalid-argument-type]


async def test_resolve_without_key_is_false_and_skips_listeners() -> None:
    lis = _make(extract_key_func=lambda update: None)
    task = await _pending(lis, MessageKey(100))
    try:
        assert await lis.resolve(make_message(100, 7, 5)) is False
        assert not task.done()
    finally:
        await _drain(task)


async def test_resolve_without_a_matching_listener_is_false() -> None:
    lis = _make()
    other = await _pending(lis, MessageKey(999))
    try:
        assert await lis.resolve(make_message(100, 7, 5)) is False
        assert not other.done()
    finally:
        await _drain(other)


async def test_resolve_hands_the_update_to_its_listener_and_removes_it() -> None:
    lis = _make()
    task = await _pending(lis, MessageKey(100, 7))
    update = make_message(100, 7, 5)

    assert await lis.resolve(update) is True
    assert lis.listeners == {}
    assert await task is update


async def test_resolve_tries_the_shapes_in_priority_order() -> None:
    lis = _make()
    anywhere = await _pending(lis, MessageKey())
    chat_wide = await _pending(lis, MessageKey(100))
    by_topic = await _pending(lis, MessageKey(100, None, 3))
    by_user = await _pending(lis, MessageKey(100, 7))
    try:
        updates = [make_message(100, 7, i, message_thread_id=3) for i in range(4)]
        for update in updates:
            assert await lis.resolve(update) is True

        assert [await task for task in (by_user, by_topic, chat_wide, anywhere)] == updates
    finally:
        await _drain(anywhere, chat_wide, by_topic, by_user)


async def test_resolve_skips_a_shape_that_sets_a_field_the_update_lacks() -> None:
    lis = _make()
    by_topic = await _pending(lis, MessageKey(100, None, 3))
    chat_wide = await _pending(lis, MessageKey(100))
    update = make_message(100, 7, 5)
    try:
        assert await lis.resolve(update) is True
        assert await chat_wide is update
        assert not by_topic.done()
    finally:
        await _drain(by_topic)


async def test_resolve_with_scope_all_hands_the_update_to_every_matching_listener() -> None:
    lis = _make(resolve_scope=ListenerScope.ALL)
    specific = await _pending(lis, MessageKey(100, 7))
    chat_wide = await _pending(lis, MessageKey(100))
    update = make_message(100, 7, 5)

    assert await lis.resolve(update) is True
    assert lis.listeners == {}
    assert await specific is update
    assert await chat_wide is update


async def test_resolve_with_scope_all_leaves_a_rejecting_listener_waiting() -> None:
    lis = _make(resolve_scope=ListenerScope.ALL)
    specific = await _pending(lis, MessageKey(100, 7), filters=TEXT_A)
    chat_wide = await _pending(lis, MessageKey(100))
    update = make_message(100, 7, 5, text="zzz")
    try:
        assert await lis.resolve(update) is True
        assert await chat_wide is update
        assert not specific.done()
        assert list(lis.listeners) == [MessageKey(100, 7)]
    finally:
        await _drain(specific)


async def test_resolve_with_scope_all_and_no_match_is_false() -> None:
    lis = _make(resolve_scope=ListenerScope.ALL)
    other = await _pending(lis, MessageKey(999))
    try:
        assert await lis.resolve(make_message(100, 7, 5)) is False
        assert not other.done()
    finally:
        await _drain(other)


async def test_resolve_skips_a_finished_listener() -> None:
    lis = _make()
    lis._add(finished := _model(MessageKey(100, 7)))
    finished.resolve("earlier")
    chat_wide = await _pending(lis, MessageKey(100))
    update = make_message(100, 7, 5)

    assert await lis.resolve(update) is True
    assert await chat_wide is update


async def test_resolve_gives_the_update_to_a_listener_its_filter_passes() -> None:
    lis = _make()
    task = await _pending(lis, MessageKey(100, 7), filters=TEXT_A)
    update = make_message(100, 7, 5, text="abc")

    assert await lis.resolve(update) is True
    assert await task is update


async def test_resolve_skips_a_lenient_rejection_and_keeps_the_listener_waiting() -> None:
    lis = _make()
    task = await _pending(lis, MessageKey(100, 7), filters=TEXT_A)
    try:
        assert await lis.resolve(make_message(100, 7, 5, text="zzz")) is False
        assert not task.done()
        assert MessageKey(100, 7) in lis.listeners
    finally:
        await _drain(task)


async def test_resolve_strict_rejection_fails_the_listener() -> None:
    lis = _make()
    task = await _pending(lis, MessageKey(100, 7), filters=TEXT_A, strict=True)
    update = make_message(100, 7, 5, text="zzz")

    assert await lis.resolve(update) is False
    with pytest.raises(ListenerRejected) as exc:
        await task
    assert exc.value.value == MessageKey(100, 7)
    assert lis.listeners == {}
    assert lis._shapes == {}


async def test_resolve_strict_filter_takes_a_passing_update() -> None:
    lis = _make(strict_filter=TEXT_A)
    task = await _pending(lis, MessageKey(100, 7))
    update = make_message(100, 7, 5, text="abc")

    assert await lis.resolve(update) is True
    assert await task is update


async def test_resolve_strict_filter_rejects_a_failing_update() -> None:
    lis = _make(strict_filter=TEXT_A)
    task = await _pending(lis, MessageKey(100, 7))

    assert await lis.resolve(make_message(100, 7, 5, text="zzz")) is False
    with pytest.raises(ListenerRejected):
        await task


@pytest.mark.parametrize("strict", [False, True])
async def test_resolve_tries_the_next_candidate_after_a_rejection(strict: bool) -> None:
    lis = _make()
    specific = await _pending(
        lis, MessageKey(100, 7), filters=filters.create(_never), strict=strict
    )
    chat_wide = await _pending(lis, MessageKey(100))
    update = make_message(100, 7, 5)
    try:
        assert await lis.resolve(update) is True
        assert await chat_wide is update
        assert specific.done() is strict
    finally:
        await _drain(specific)


async def test_resolve_skips_a_listener_taken_while_its_filter_ran() -> None:
    async def slow_pass(_: object, __: object, update: Message) -> bool:
        await asyncio.sleep(0.01)
        return True

    lis = _make()
    task = await _pending(lis, MessageKey(100, 7), filters=filters.create(slow_pass))
    first, second = make_message(100, 7, 5), make_message(100, 7, 6)

    results = await asyncio.gather(lis.resolve(first), lis.resolve(second))

    assert results == [True, False]
    assert await task is first
    assert lis.listeners == {}


async def test_resolve_runs_a_sync_filter_on_the_client_executor() -> None:
    seen: list[str] = []

    def record(_: object, __: object, update: Message) -> bool:
        seen.append(threading.current_thread().name)
        return True

    executor = ThreadPoolExecutor(1, thread_name_prefix="pyroflow-filter")
    lis = _make()
    try:
        task = await _pending(lis, MessageKey(100, 7), filters=filters.create(record))
        update = make_message(100, 7, 5, _client=SimpleNamespace(executor=executor))

        assert await lis.resolve(update) is True
        assert await task is update
        assert seen[0].startswith("pyroflow-filter")
    finally:
        executor.shutdown()


async def test_resolve_treats_a_failing_filter_as_a_rejection(
    caplog: pytest.LogCaptureFixture,
) -> None:
    async def boom(_: object, __: object, update: Message) -> bool:
        msg = "filter broke"
        raise RuntimeError(msg)

    lis = _make()
    task = await _pending(lis, MessageKey(100, 7), filters=filters.create(boom))
    try:
        with caplog.at_level(logging.ERROR):
            assert await lis.resolve(make_message(100, 7, 5)) is False
        assert "filter broke" in caplog.text
        assert not task.done()
    finally:
        await _drain(task)


# --- a key class with a field of its own -----------------------------------------


@dataclasses.dataclass(frozen=True, slots=True)
class _LanguageKey(MessageKey):
    language: str | None = None


class _LanguageListener(UpdateListener[Message, _LanguageKey]):
    __update_type__ = Message
    __key_type__ = _LanguageKey


async def test_a_key_class_with_a_field_of_its_own_needs_no_listener_change() -> None:
    lis = _LanguageListener(
        extract_key_func=lambda u: _LanguageKey(u.chat.id, language=u.from_user.language_code)
    )
    by_language = await _pending(lis, _LanguageKey(100, language="en"))
    chat_wide = await _pending(lis, _LanguageKey(100))
    english = make_message(100, 7, 5)
    english.from_user.language_code = "en"
    french = make_message(100, 7, 6)
    french.from_user.language_code = "fr"

    assert lis._shape_order == (CHAT | 0b100000, CHAT)
    assert await lis.resolve(french) is True
    assert await lis.resolve(english) is True
    assert await by_language is english
    assert await chat_wide is french


# --- extract_key ----------------------------------------------------------------


def test_extract_key_requires_func_or_override() -> None:
    lis = _Listener()
    with pytest.raises(NotImplementedError, match="_Listener must either pass extract_key_func"):
        lis.extract_key(make_message())


def test_extract_key_rejects_the_wrong_update_type() -> None:
    with pytest.raises(TypeError):
        _make().extract_key("not a message")  # ty: ignore[invalid-argument-type]


def test_extract_key_rejects_a_key_of_another_type() -> None:
    lis = _make(extract_key_func=lambda update: (update.chat.id,))

    with pytest.raises(TypeError, match="must return exactly a MessageKey or None, not tuple"):
        lis.extract_key(make_message())


def test_extract_key_rejects_a_subclass_key() -> None:
    lis = _make(extract_key_func=lambda update: _LanguageKey(update.chat.id))

    with pytest.raises(
        TypeError, match="must return exactly a MessageKey or None, not _LanguageKey"
    ):
        lis.extract_key(make_message())


def test_extract_key_calls_the_func_inline() -> None:
    update = make_message(100, 7, 5)
    thread = threading.current_thread().name
    seen: list[str] = []

    def key_of(update: Message) -> MessageKey:
        seen.append(threading.current_thread().name)
        return _chat_key(update)

    key = _make(extract_key_func=key_of).extract_key(update)

    assert not inspect.isawaitable(key)
    assert key == MessageKey(100)
    assert seen == [thread]
    assert _make().extract_key(update) == MessageKey(100, 7)


# --- ephemeral updates --------------------------------------------------------


async def test_an_ephemeral_update_reaches_only_a_wait_on_ephemeral() -> None:
    lis = MessageListener()
    ephemeral = make_message(message_id=0, ephemeral_message_id=4)
    regular_waits = [
        asyncio.create_task(lis.listen()),
        asyncio.create_task(lis.listen(chat_id=100)),
        asyncio.create_task(lis.listen(chat_id=100, user_id=7)),
    ]
    wait = asyncio.create_task(lis.listen(chat_id=100, user_id=7, ephemeral=True))
    await asyncio.sleep(0)

    assert await lis.resolve(ephemeral) is True

    assert await wait is ephemeral
    assert not any(task.done() for task in regular_waits)
    await lis.stop()
    await asyncio.gather(*regular_waits, return_exceptions=True)


async def test_a_regular_update_never_reaches_a_wait_on_ephemeral() -> None:
    lis = MessageListener()
    wait = asyncio.create_task(lis.listen(chat_id=100, user_id=7, ephemeral=True))
    await asyncio.sleep(0)

    assert await lis.resolve(make_message()) is False

    assert not wait.done()
    await lis.stop()
    await asyncio.gather(wait, return_exceptions=True)
