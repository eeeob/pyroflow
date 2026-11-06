"""Behavioural tests for UpdateListener.

Covers key matching and the default timeout using the real MessageListener,
then every UpdateListener element directly through a minimal local subclass.
"""

from __future__ import annotations as _annotations

import asyncio
import gc
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
    ListenerTimeout,
    ListenerWorkersBusy,
)
from pyroflow.models import ListenerContext, ListenerKey, ListenerModel
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


def _model(key: ListenerKey) -> ListenerModel:
    return ListenerModel(key, asyncio.get_running_loop().create_future())


def _never(_: object, __: object, update: Message) -> bool:
    return False


async def _starts_with_a(_: object, __: object, update: Message) -> bool:
    return (update.text or "").startswith("a")


TEXT_A = filters.create(_starts_with_a)
"""Filter: text starting with `a`."""


async def _chat_key(update: Message) -> ListenerKey:
    return ListenerKey(update.chat.id)


def test_module_exports() -> None:
    assert update_listener_module.__all__ == ("UpdateListener",)


# --- __init__ -----------------------------------------------------------------


def test_init_defaults() -> None:
    lis = _Listener()
    assert lis.duplicate_policy is DuplicatePolicy.REPLACE
    assert lis.extract_key_func is None
    assert lis.on_error_func is None
    assert lis.on_listen_func is None
    assert lis.timeout is None
    assert lis.resolve_scope is ListenerScope.FIRST
    assert lis.listeners == {}
    assert lis.is_closed is False


def test_init_stores_arguments() -> None:
    lis = _Listener(
        duplicate_policy=DuplicatePolicy.REJECT,
        extract_key_func=_key_of,
        on_error_func=print,
        on_listen_func=dict,
        timeout=3,
        resolve_scope=ListenerScope.ALL,
    )
    assert lis.duplicate_policy is DuplicatePolicy.REJECT
    assert lis.extract_key_func is _key_of
    assert lis.on_error_func is print
    assert lis.on_listen_func is dict
    assert lis.timeout == 3
    assert lis.resolve_scope is ListenerScope.ALL


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


# --- cancel / reject -----------------------------------------------------------


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
    lis.listeners[ListenerKey(2)] = done = _model(ListenerKey(2))
    done.resolve("update")

    assert lis.cancel(ListenerKey(1)) is False
    assert lis.cancel(ListenerKey(2)) is True
    assert await done.future == "update"


async def test_reject_fails_the_waiter_with_the_update_and_removes_it() -> None:
    lis = _make()
    task = await _pending(lis, 1)
    update = make_message(1)

    assert lis.reject(ListenerKey(1), update) is True
    assert ListenerKey(1) not in lis.listeners
    with pytest.raises(ListenerRejected) as exc:
        await task
    assert exc.value.update is update


async def test_reject_without_a_listener_is_false_and_leaves_a_finished_one_as_is() -> None:
    lis = _make()
    lis.listeners[ListenerKey(2)] = done = _model(ListenerKey(2))
    done.resolve("update")

    assert lis.reject(ListenerKey(1), make_message()) is False
    assert lis.reject(ListenerKey(2), make_message()) is True
    assert await done.future == "update"


async def test_evict_fails_the_waiter_with_listener_evicted_and_removes_it() -> None:
    lis = _make()
    task = await _pending(lis, 100)
    model = lis.listeners[ListenerKey(100)]

    assert lis.evict(ListenerKey(100), model=model) is True
    with pytest.raises(ListenerEvicted):
        await task
    assert lis.listeners == {}


async def test_evict_spares_a_newer_wait_and_a_missing_key() -> None:
    lis = _make()
    task = await _pending(lis, 100)
    try:
        assert lis.evict(ListenerKey(100), model=_model(ListenerKey(100))) is False
        assert lis.evict(ListenerKey(999)) is False
        assert not task.done()
    finally:
        await _drain(task)


# --- listen ---------------------------------------------------------------------


class _Holder:
    """Stands in for the dispatcher of a worker: records what `listen` does with it."""

    def __init__(self, error: Exception | None = None, *, has_policy: bool = True) -> None:
        self.error = error
        self.workers_policy = object() if has_policy else None
        self.handler_waits: dict[asyncio.Future, tuple[object, ListenerModel, object]] = {}
        self.entered: list[ListenerKey] = []
        self.ended: list[tuple[object, ListenerModel, object]] = []
        self.released: list[object] = []

    async def enter_handler_wait(self, policy: object, key: ListenerKey) -> None:
        if self.error is not None:
            raise self.error
        self.entered.append(key)

    def end_handler_wait(self, future: asyncio.Future) -> None:
        self.ended.append(self.handler_waits.pop(future))

    def release_evicted_worker(self, worker: object) -> None:
        self.released.append(worker)


def _as_worker(holder: _Holder) -> object:
    """Mark the running task as a worker of `holder`, as `Dispatcher.handler_worker` does."""
    return _HANDLER_WORKER.set((holder, asyncio.current_task()))


async def test_listen_in_a_worker_task_tracks_the_wait_until_it_ends() -> None:
    holder = _Holder()
    token = _as_worker(holder)
    try:
        lis = _make()
        with pytest.raises(ListenerTimeout):
            await lis.listen(100, timeout=0.01)
    finally:
        _HANDLER_WORKER.reset(token)

    assert holder.entered == [ListenerKey(100)]
    ((listener, model, worker),) = holder.ended
    assert listener is lis
    assert model.key == ListenerKey(100)
    assert worker is asyncio.current_task()
    assert holder.released == [worker]
    assert holder.handler_waits == {}


async def test_listen_in_a_task_the_handler_spawned_holds_no_worker() -> None:
    holder = _Holder()
    token = _as_worker(holder)
    try:
        lis = _make()
        with pytest.raises(ListenerTimeout):
            await asyncio.create_task(lis.listen(100, timeout=0.01))
    finally:
        _HANDLER_WORKER.reset(token)

    assert holder.entered == []


async def test_listen_without_a_policy_leaves_the_dispatcher_alone() -> None:
    holder = _Holder(has_policy=False)
    token = _as_worker(holder)
    try:
        with pytest.raises(ListenerTimeout):
            await _make().listen(100, timeout=0.01)
    finally:
        _HANDLER_WORKER.reset(token)

    assert holder.entered == []
    assert holder.ended == []


async def test_listen_refused_by_the_policy_registers_nothing() -> None:
    token = _as_worker(_Holder(error=ListenerWorkersBusy(ListenerKey(100))))
    try:
        lis = _make()
        with pytest.raises(ListenerWorkersBusy):
            await lis.listen(100)
    finally:
        _HANDLER_WORKER.reset(token)

    assert lis.listeners == {}


async def test_listen_refuses_a_duplicate_before_making_room_for_it() -> None:
    lis = _make(duplicate_policy=DuplicatePolicy.REJECT)
    first = await _pending(lis, 100)
    holder = _Holder()
    token = _as_worker(holder)
    try:
        with pytest.raises(ListenerAlreadyExists):
            await lis.listen(100)
    finally:
        _HANDLER_WORKER.reset(token)
        await _drain(first)

    assert holder.entered == []
    assert holder.handler_waits == {}
    assert holder.ended == []


async def test_listen_replacing_a_wait_that_holds_a_worker_needs_no_room() -> None:
    lis = _make()
    first = await _pending(lis, 100)
    model = lis.listeners[ListenerKey(100)]
    holder = _Holder()
    holder.handler_waits[model.future] = (lis, model, asyncio.current_task())
    token = _as_worker(holder)
    try:
        with pytest.raises(ListenerTimeout):
            await lis.listen(100, timeout=0.01)
    finally:
        _HANDLER_WORKER.reset(token)
        await _drain(first)

    assert holder.entered == []


async def test_listen_replacing_a_wait_that_holds_no_worker_makes_room() -> None:
    lis = _make()
    first = await _pending(lis, 100)
    holder = _Holder()
    token = _as_worker(holder)
    try:
        with pytest.raises(ListenerTimeout):
            await lis.listen(100, timeout=0.01)
    finally:
        _HANDLER_WORKER.reset(token)
        await _drain(first)

    assert holder.entered == [ListenerKey(100)]


async def test_listen_without_context_attaches_none() -> None:
    lis = _make()
    task = await _pending(lis, 1)
    try:
        assert lis.listeners[ListenerKey(1)].context is None
    finally:
        await _drain(task)


@pytest.mark.parametrize("end", ["timeout", "cancel"])
async def test_listen_leaves_no_reference_cycle_once_the_wait_fails(end: str) -> None:
    # Without the cyclic GC, the wait's future must die with the error that ended it.
    lis = _make()
    gc.disable()
    try:
        task = await _pending(lis, 1, timeout=0.02 if end == "timeout" else None)
        future = weakref.ref(lis.listeners[ListenerKey(1)].future)

        if end == "cancel":
            lis.cancel(ListenerKey(1))

        with pytest.raises(ListenerTimeout if end == "timeout" else ListenerCancelled):
            await task

        del task
        assert future() is None
    finally:
        gc.enable()


async def test_listen_registers_the_listener_before_yielding() -> None:
    lis = _make()
    context = ListenerContext(step=1)
    coro = lis.listen(1, 2, 3, context=context)
    task = asyncio.ensure_future(coro)
    # One loop turn starts the coroutine; it registers before it first waits.
    await asyncio.sleep(0)
    key = ListenerKey(1, 2, 3)
    try:
        listener = lis.listeners[key]
        assert listener.key == key
        assert listener.context is context
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
    lis.listeners[ListenerKey(1)] = finished = _model(ListenerKey(1))
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


async def test_listen_stores_the_filter_and_strict_on_the_model() -> None:
    lis = _make()
    task = await _pending(lis, 1, filters=TEXT_A, strict=True)
    try:
        listener = lis.listeners[ListenerKey(1)]
        assert listener.filters is TEXT_A
        assert listener.strict is True
    finally:
        await _drain(task)


@pytest.mark.parametrize(
    ("end", "error"),
    [
        (lambda lis, key: None, ListenerTimeout),
        (lambda lis, key: lis.cancel(key), ListenerCancelled),
        (lambda lis, key: lis.reject(key, "update"), ListenerRejected),
    ],
)
async def test_listen_reports_the_error_that_ended_the_wait(
    end: Any, error: type[Exception]
) -> None:
    seen: list[tuple[object, object]] = []
    lis = _make(on_error_func=lambda exc, model: seen.append((exc, model)))
    task = await _pending(lis, 1, timeout=0.05)
    model = lis.listeners[ListenerKey(1)]

    end(lis, ListenerKey(1))
    with pytest.raises(error) as exc:
        await task

    assert seen == [(exc.value, model)]


async def test_listen_reports_to_an_async_func_after_removing_the_wait() -> None:
    seen: list[bool] = []
    lis = _make()

    async def record(exc: object, model: object) -> None:
        seen.append(ListenerKey(1) in lis.listeners)

    lis.on_error_func = record
    with pytest.raises(ListenerTimeout):
        await lis.listen(1, timeout=0.01)

    assert seen == [False]


async def test_listen_logs_a_failing_on_error_func_and_raises_the_error(
    caplog: pytest.LogCaptureFixture,
) -> None:
    def boom(exc: object, model: object) -> None:
        msg = "boom"
        raise RuntimeError(msg)

    with caplog.at_level(logging.ERROR), pytest.raises(ListenerTimeout):
        await _make(on_error_func=boom).listen(1, timeout=0.01)
    assert "boom" in caplog.text


async def test_listen_does_not_report_an_error_raised_before_the_wait() -> None:
    seen: list[object] = []
    lis = _make(
        duplicate_policy=DuplicatePolicy.REJECT, on_error_func=lambda exc, m: seen.append(exc)
    )
    first = await _pending(lis, 1)
    try:
        with pytest.raises(ListenerAlreadyExists):
            await lis.listen(1)
        assert seen == []
    finally:
        await _drain(first)


async def test_listen_passes_its_arguments_to_on_listen_func_before_registering() -> None:
    seen: list[tuple[dict[str, object], bool]] = []
    lis = _make()
    lis.on_listen_func = lambda kw: seen.append((kw, ListenerKey(1, 2, 3) in lis.listeners))

    context = ListenerContext(a=1)
    task = await _pending(lis, 1, 2, 3, context=context, filters=TEXT_A, strict=True, timeout=5)
    await _drain(task)

    assert seen == [
        (
            {
                "chat_id": 1,
                "user_id": 2,
                "message_id": 3,
                "context": context,
                "filters": TEXT_A,
                "strict": True,
                "timeout": 5,
            },
            False,
        )
    ]


async def test_listen_starts_no_wait_when_on_listen_func_raises() -> None:
    def refuse(kw: object) -> None:
        msg = "refused"
        raise ValueError(msg)

    lis = _make(on_listen_func=refuse)

    with pytest.raises(ValueError, match="refused"):
        await lis.listen(1)
    assert lis.listeners == {}


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


async def test_resolve_with_scope_all_hands_the_update_to_every_matching_listener() -> None:
    lis = _make(resolve_scope=ListenerScope.ALL)
    specific = await _pending(lis, 100, 7)
    chat_wide = await _pending(lis, 100)
    update = make_message(100, 7, 5)

    assert await lis.resolve(update) is True
    assert lis.listeners == {}
    assert await specific is update
    assert await chat_wide is update


async def test_resolve_with_scope_all_leaves_a_rejecting_listener_waiting() -> None:
    lis = _make(resolve_scope=ListenerScope.ALL)
    specific = await _pending(lis, 100, 7, filters=TEXT_A)
    chat_wide = await _pending(lis, 100)
    update = make_message(100, 7, 5, text="zzz")
    try:
        assert await lis.resolve(update) is True
        assert await chat_wide is update
        assert not specific.done()
        assert list(lis.listeners) == [ListenerKey(100, 7)]
    finally:
        await _drain(specific)


async def test_resolve_with_scope_all_and_no_match_is_false() -> None:
    lis = _make(resolve_scope=ListenerScope.ALL)
    other = await _pending(lis, 999)
    try:
        assert await lis.resolve(make_message(100, 7, 5)) is False
        assert not other.done()
    finally:
        await _drain(other)


async def test_resolve_skips_a_finished_listener() -> None:
    lis = _make()
    lis.listeners[ListenerKey(100, 7, 5)] = finished = _model(ListenerKey(100, 7, 5))
    finished.resolve("earlier")
    chat_wide = await _pending(lis, 100)
    update = make_message(100, 7, 5)

    assert await lis.resolve(update) is True
    assert await chat_wide is update


async def test_resolve_gives_the_update_to_a_listener_its_filter_passes() -> None:
    lis = _make()
    task = await _pending(lis, 100, 7, filters=TEXT_A)
    update = make_message(100, 7, 5, text="abc")

    assert await lis.resolve(update) is True
    assert await task is update


async def test_resolve_skips_a_lenient_rejection_and_keeps_the_listener_waiting() -> None:
    lis = _make()
    task = await _pending(lis, 100, 7, filters=TEXT_A)
    try:
        assert await lis.resolve(make_message(100, 7, 5, text="zzz")) is False
        assert not task.done()
        assert ListenerKey(100, 7) in lis.listeners
    finally:
        await _drain(task)


async def test_resolve_strict_rejection_fails_the_listener_with_the_update() -> None:
    lis = _make()
    task = await _pending(lis, 100, 7, filters=TEXT_A, strict=True)
    update = make_message(100, 7, 5, text="zzz")

    assert await lis.resolve(update) is False
    with pytest.raises(ListenerRejected) as exc:
        await task
    assert exc.value.value == ListenerKey(100, 7)
    assert exc.value.update is update
    assert lis.listeners == {}


@pytest.mark.parametrize("strict", [False, True])
async def test_resolve_tries_the_next_candidate_after_a_rejection(strict: bool) -> None:
    lis = _make()
    specific = await _pending(lis, 100, 7, filters=filters.create(_never), strict=strict)
    chat_wide = await _pending(lis, 100)
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
    task = await _pending(lis, 100, 7, filters=filters.create(slow_pass))
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
        task = await _pending(lis, 100, 7, filters=filters.create(record))
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
    task = await _pending(lis, 100, 7, filters=filters.create(boom))
    try:
        with caplog.at_level(logging.ERROR):
            assert await lis.resolve(make_message(100, 7, 5)) is False
        assert "filter broke" in caplog.text
        assert not task.done()
    finally:
        await _drain(task)


# --- extract_key ----------------------------------------------------------------


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
