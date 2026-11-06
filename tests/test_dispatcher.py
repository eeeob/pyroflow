"""Dispatcher: listener registry, lifecycle, and the route of an update.

Each update goes to the listener of its type first; one it takes stops
there, any other runs through the handler groups as in Pyrogram.
"""

from __future__ import annotations as _annotations

import asyncio
import logging
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any

import pytest

from pyrogram import ContinuePropagation, StopPropagation
from pyrogram.handlers import (
    CallbackQueryHandler,
    ErrorHandler,
    MessageHandler,
    RawUpdateHandler,
)
from pyrogram.raw.types import UpdateConfig, UpdateLoginToken
from pyrogram.types import Message

import pyroflow
from pyroflow import dispatcher as dispatcher_module
from pyroflow.dispatcher import Dispatcher
from pyroflow.enums import WorkersBusyMode
from pyroflow.errors import (
    ListenerCancelled,
    ListenerEvicted,
    ListenerTimeout,
    ListenerWorkersBusy,
)
from pyroflow.models import ListenerKey, ListenerModel, WorkersPolicy
from pyroflow.update_listener import MessageListener
from pyroflow.utils import handler_worker_var

from .conftest import make_callback_query, make_message

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable


# --- module-level definitions ----------------------------------------------


def test_module_logger_is_named_after_the_module() -> None:
    assert dispatcher_module.log.name == "pyroflow.dispatcher"


def test_public_surface() -> None:
    assert dispatcher_module.__all__ == ("Dispatcher",)


# --- Dispatcher: construction, start and stop -------------------------------


class FakeListener:
    """A listener stand-in bound to `Message`: records its lifecycle and what it resolves."""

    __update_type__ = Message

    def __init__(
        self,
        log: list[str] | None = None,
        name: str = "listener",
        error: Exception | None = None,
        *,
        resolves: bool = True,
    ) -> None:
        self.log = [] if log is None else log
        self.name = name
        self.error = error
        self.resolves = resolves
        self.resolved: list[object] = []

    async def start(self) -> None:
        self.log.append(f"start {self.name}")
        if self.error is not None:
            raise self.error

    async def stop(self) -> None:
        self.log.append(f"stop {self.name}")
        if self.error is not None:
            raise self.error

    async def resolve(self, update: object) -> bool:
        self.resolved.append(update)
        if self.error is not None:
            raise self.error
        return self.resolves


def make_client(**kw: Any) -> SimpleNamespace:
    kw.setdefault("loop", asyncio.get_running_loop())
    kw.setdefault("workers", 0)
    return SimpleNamespace(
        executor=None,
        start_handler=None,
        stop_handler=None,
        no_updates=True,
        skip_updates=True,
        **kw,
    )


def make_real_dispatcher(**kw: Any) -> Dispatcher:
    return Dispatcher(make_client(**kw))


async def test_init_runs_the_original_and_sets_an_empty_registry() -> None:
    client = make_client()
    dispatcher = Dispatcher(client)

    assert dispatcher.client is client
    assert isinstance(dispatcher.updates_queue, asyncio.Queue)
    assert dispatcher.listeners == {}
    assert dispatcher.is_started is False


async def test_start_and_stop_through_the_original_dispatcher() -> None:
    dispatcher = make_real_dispatcher()

    await dispatcher.start()
    assert dispatcher.is_started is True

    await dispatcher.stop()
    assert dispatcher.is_started is False


async def test_start_runs_the_listeners_then_the_original() -> None:
    order: list[str] = []
    dispatcher = make_real_dispatcher()

    async def oldstart(*args: object, **kw: object) -> object:
        order.append(f"oldstart {args} {kw}")
        assert dispatcher.is_started is False
        return "result"

    dispatcher.oldstart = oldstart
    dispatcher.listeners[Message] = FakeListener(order)  # ty: ignore[invalid-assignment]

    assert await dispatcher.start(1, flag=True) == "result"

    assert dispatcher.is_started is True
    assert order == ["start listener", "oldstart (1,) {'flag': True}"]


async def test_start_survives_a_failing_listener() -> None:
    order: list[str] = []
    dispatcher = make_real_dispatcher()
    dispatcher.listeners[Message] = FakeListener(order, error=RuntimeError("x"))  # ty: ignore[invalid-assignment]

    await dispatcher.start()

    assert dispatcher.is_started is True
    assert order == ["start listener"]


async def test_start_leaves_the_dispatcher_stopped_if_the_original_fails() -> None:
    dispatcher = make_real_dispatcher()

    async def oldstart() -> None:
        msg = "boom"
        raise RuntimeError(msg)

    dispatcher.oldstart = oldstart

    with pytest.raises(RuntimeError):
        await dispatcher.start()

    assert dispatcher.is_started is False


async def test_stop_stops_the_listeners_then_the_original() -> None:
    order: list[str] = []
    dispatcher = make_real_dispatcher()
    dispatcher.is_started = True

    async def oldstop(*args: object, **kw: object) -> object:
        order.append(f"oldstop {args} {kw}")
        assert dispatcher.is_started is True
        return "result"

    dispatcher.oldstop = oldstop
    dispatcher.listeners[Message] = FakeListener(order, error=RuntimeError("x"))  # ty: ignore[invalid-assignment]

    assert await dispatcher.stop(clear_handlers=False) == "result"

    assert dispatcher.is_started is False
    assert order == ["stop listener", "oldstop () {'clear_handlers': False}"]


async def test_stop_lets_a_handler_waiting_in_listen_finish_before_draining() -> None:
    dispatcher = make_real_dispatcher()
    listener = MessageListener()
    dispatcher.register_listener(listener)
    waiter = asyncio.create_task(listener.listen(100, 7))
    await asyncio.sleep(0.01)

    async def oldstop() -> None:
        # The original stop drains the workers; a handler blocked in `listen` must be released by now.
        await asyncio.sleep(0)
        assert waiter.done()

    dispatcher.oldstop = oldstop

    await dispatcher.stop()

    with pytest.raises(ListenerCancelled):
        await waiter


# --- Dispatcher: registration -----------------------------------------------


async def test_register_listener_stores_it_by_update_type() -> None:
    dispatcher = make_real_dispatcher()
    listener = FakeListener()

    dispatcher.register_listener(listener)  # ty: ignore[invalid-argument-type]

    assert dispatcher.listeners == {Message: listener}


async def test_register_listener_rejects_a_second_for_the_same_type() -> None:
    dispatcher = make_real_dispatcher()
    first = FakeListener()
    dispatcher.register_listener(first)  # ty: ignore[invalid-argument-type]

    with pytest.raises(ValueError, match="UpdateListener for .* is already registered"):
        dispatcher.register_listener(FakeListener())  # ty: ignore[invalid-argument-type]

    assert dispatcher.listeners == {Message: first}


async def test_register_listener_rejects_a_running_dispatcher() -> None:
    dispatcher = make_real_dispatcher()
    dispatcher.is_started = True

    with pytest.raises(RuntimeError, match="Cannot register listener while dispatcher"):
        dispatcher.register_listener(FakeListener())  # ty: ignore[invalid-argument-type]

    assert dispatcher.listeners == {}


async def test_unregister_listener_removes_and_stops_it() -> None:
    order: list[str] = []
    dispatcher = make_real_dispatcher()
    dispatcher.listeners[Message] = FakeListener(order)  # ty: ignore[invalid-assignment]

    await dispatcher.unregister_listener(Message)

    assert dispatcher.listeners == {}
    assert order == ["stop listener"]


async def test_unregister_listener_of_an_unknown_type_is_a_noop() -> None:
    order: list[str] = []
    dispatcher = make_real_dispatcher()
    listener = FakeListener(order)
    dispatcher.listeners[Message] = listener  # ty: ignore[invalid-assignment]

    await dispatcher.unregister_listener(int)

    assert dispatcher.listeners == {Message: listener}
    assert order == []


# --- Dispatcher.handle_listen -----------------------------------------------


async def test_handle_listen_is_true_for_an_update_the_listener_took() -> None:
    dispatcher = make_real_dispatcher()
    listener = FakeListener()
    dispatcher.listeners[Message] = listener  # ty: ignore[invalid-assignment]
    msg = make_message()

    assert await dispatcher.handle_listen(msg) is True
    assert listener.resolved == [msg]


async def test_handle_listen_unmatched_update_propagates_on(
    caplog: pytest.LogCaptureFixture,
) -> None:
    dispatcher = make_real_dispatcher()
    listener = FakeListener(resolves=False)
    dispatcher.listeners[Message] = listener  # ty: ignore[invalid-assignment]
    msg = make_message()

    with caplog.at_level(logging.ERROR, logger="pyroflow.dispatcher"):
        assert await dispatcher.handle_listen(msg) is False

    assert listener.resolved == [msg]
    assert "Unexpected error in handle_listen" not in caplog.text


async def test_handle_listen_lets_an_update_through_an_idle_listener() -> None:
    dispatcher = make_real_dispatcher()
    dispatcher.register_listener(MessageListener())

    assert await dispatcher.handle_listen(make_message()) is False


async def test_handle_listen_logs_a_listener_error(caplog: pytest.LogCaptureFixture) -> None:
    dispatcher = make_real_dispatcher()
    dispatcher.listeners[Message] = FakeListener(error=RuntimeError("boom"))  # ty: ignore[invalid-assignment]

    with caplog.at_level(logging.ERROR, logger="pyroflow.dispatcher"):
        assert await dispatcher.handle_listen(make_message()) is False

    assert "Unexpected error in handle_listen" in caplog.text


async def test_handle_listen_dispatches_on_the_exact_type() -> None:
    dispatcher = make_real_dispatcher()
    listener = FakeListener()
    dispatcher.listeners[Message] = listener  # ty: ignore[invalid-assignment]

    assert await dispatcher.handle_listen(make_callback_query()) is False
    assert listener.resolved == []


# --- Dispatcher.handle_update -----------------------------------------------

RAW_PACKET = ("raw-update", {"users": 1}, {"chats": 2})


def recording(
    calls: list[tuple[object, ...]], name: str, error: BaseException | None = None
) -> Callable[..., Awaitable[None]]:
    async def callback(client: object, *args: object) -> None:
        calls.append((name, *args))
        if error is not None:
            raise error

    return callback


def failing_check(error: Exception) -> Callable[..., Awaitable[bool]]:
    async def check(client: object, update: object) -> bool:
        raise error

    return check


def capture_handler_exceptions(dispatcher: Dispatcher) -> list[tuple[object, ...]]:
    seen: list[tuple[object, ...]] = []

    async def handle(exc: Exception, handler: object, *rest: object) -> None:
        seen.append((exc, handler, *rest))

    dispatcher.handle_update_handler_exception = handle
    return seen


async def test_runs_the_first_matching_handler_of_each_group() -> None:
    dispatcher = make_real_dispatcher()
    calls: list[tuple[object, ...]] = []
    msg = make_message()
    dispatcher.groups[0] = [
        MessageHandler(recording(calls, "a")),
        MessageHandler(recording(calls, "b")),
    ]
    dispatcher.groups[1] = [MessageHandler(recording(calls, "c"))]

    result = await dispatcher.handle_update(RAW_PACKET, msg, MessageHandler)

    assert result is None
    assert calls == [("a", msg), ("c", msg)]


async def test_skips_error_handlers_and_handlers_of_another_type() -> None:
    dispatcher = make_real_dispatcher()
    calls: list[tuple[object, ...]] = []
    msg = make_message()
    dispatcher.groups[0] = [
        ErrorHandler(recording(calls, "error")),
        CallbackQueryHandler(recording(calls, "callback")),
        MessageHandler(recording(calls, "message")),
    ]

    assert await dispatcher.handle_update(RAW_PACKET, msg, MessageHandler) is None
    assert calls == [("message", msg)]


async def test_handler_whose_filter_rejects_is_skipped() -> None:
    dispatcher = make_real_dispatcher()
    calls: list[tuple[object, ...]] = []
    rejecting = MessageHandler(recording(calls, "rejecting"))

    async def reject(client: object, update: object) -> bool:
        return False

    rejecting.check = reject
    dispatcher.groups[0] = [rejecting]

    assert await dispatcher.handle_update(RAW_PACKET, make_message(), MessageHandler) is None
    assert calls == []


async def test_raw_handler_receives_the_raw_packet() -> None:
    dispatcher = make_real_dispatcher()
    calls: list[tuple[object, ...]] = []
    dispatcher.groups[0] = [RawUpdateHandler(recording(calls, "raw"))]

    assert await dispatcher.handle_update(RAW_PACKET, None, type(None)) is None
    assert calls == [("raw", *RAW_PACKET)]


async def test_handle_update_leaves_the_listener_alone() -> None:
    dispatcher = make_real_dispatcher()
    calls: list[tuple[object, ...]] = []
    listener = FakeListener()
    dispatcher.listeners[Message] = listener  # ty: ignore[invalid-assignment]
    dispatcher.groups[0] = [MessageHandler(recording(calls, "a"))]
    msg = make_message()

    await dispatcher.handle_update(RAW_PACKET, msg, MessageHandler)

    assert listener.resolved == []
    assert calls == [("a", msg)]


@pytest.mark.parametrize(
    ("handler_cls", "message"),
    [
        (MessageHandler, "Error in handler.check"),
        (RawUpdateHandler, "Error in raw handler.check"),
    ],
)
async def test_failing_check_is_logged_and_the_next_handler_runs(
    handler_cls: type[MessageHandler | RawUpdateHandler],
    message: str,
    caplog: pytest.LogCaptureFixture,
) -> None:
    dispatcher = make_real_dispatcher()
    calls: list[tuple[object, ...]] = []
    msg = make_message()
    broken = handler_cls(recording(calls, "broken"))
    broken.check = failing_check(RuntimeError("check"))
    dispatcher.groups[0] = [broken, MessageHandler(recording(calls, "next"))]

    with caplog.at_level(logging.ERROR, logger="pyroflow.dispatcher"):
        result = await dispatcher.handle_update(RAW_PACKET, msg, MessageHandler)

    assert result is None
    assert calls == [("next", msg)]
    assert message in caplog.text


async def test_continue_propagation_tries_the_next_handler() -> None:
    dispatcher = make_real_dispatcher()
    calls: list[tuple[object, ...]] = []
    msg = make_message()
    dispatcher.groups[0] = [
        MessageHandler(recording(calls, "a", ContinuePropagation())),
        MessageHandler(recording(calls, "b")),
    ]

    assert await dispatcher.handle_update(RAW_PACKET, msg, MessageHandler) is None
    assert calls == [("a", msg), ("b", msg)]


async def test_stop_propagation_propagates_out() -> None:
    error = StopPropagation()
    dispatcher = make_real_dispatcher()
    calls: list[tuple[object, ...]] = []
    msg = make_message()
    dispatcher.groups[0] = [MessageHandler(recording(calls, "a", error))]
    dispatcher.groups[1] = [MessageHandler(recording(calls, "b"))]

    with pytest.raises(type(error)):
        await dispatcher.handle_update(RAW_PACKET, msg, MessageHandler)

    assert calls == [("a", msg)]


async def test_handler_error_is_reported_then_the_group_ends() -> None:
    dispatcher = make_real_dispatcher()
    seen = capture_handler_exceptions(dispatcher)
    calls: list[tuple[object, ...]] = []
    msg = make_message()
    error = RuntimeError("boom")
    broken = MessageHandler(recording(calls, "broken", error))
    dispatcher.groups[0] = [broken, MessageHandler(recording(calls, "same-group"))]
    dispatcher.groups[1] = [MessageHandler(recording(calls, "other-group"))]

    assert await dispatcher.handle_update(RAW_PACKET, msg, MessageHandler) is None
    assert calls == [("broken", msg), ("other-group", msg)]
    assert seen == [(error, broken, *RAW_PACKET)]


# --- Dispatcher.handler_worker ----------------------------------------------


class FakeRawUpdate:
    pass


async def test_handler_worker_parses_and_dispatches_under_the_lock() -> None:
    dispatcher = make_real_dispatcher()
    lock = asyncio.Lock()
    packet = (FakeRawUpdate(), {}, {})
    seen: list[tuple[object, ...]] = []

    async def parser(update: object, users: object, chats: object) -> tuple[object, type]:
        return ("parsed", MessageHandler)

    async def handle_update(packet: object, parsed: object, handler_type: object) -> None:
        seen.append((packet, parsed, handler_type, lock.locked()))

    dispatcher.update_parsers = {FakeRawUpdate: parser}
    dispatcher.handle_update = handle_update
    dispatcher.updates_queue.put_nowait(packet)
    dispatcher.updates_queue.put_nowait(None)

    await dispatcher.handler_worker(lock)

    assert seen == [(packet, "parsed", MessageHandler, True)]
    assert lock.locked() is False


async def test_handler_worker_resolves_a_listened_update_without_the_lock() -> None:
    dispatcher = make_real_dispatcher()
    lock = asyncio.Lock()
    listener = FakeListener()
    dispatcher.listeners[Message] = listener  # ty: ignore[invalid-assignment]
    msg = make_message()
    handled: list[object] = []

    async def parser(update: object, users: object, chats: object) -> tuple[object, type]:
        return (msg, MessageHandler)

    async def handle_update(packet: object, parsed: object, handler_type: object) -> None:
        handled.append(parsed)

    dispatcher.update_parsers = {FakeRawUpdate: parser}
    dispatcher.handle_update = handle_update
    dispatcher.updates_queue.put_nowait((FakeRawUpdate(), {}, {}))
    dispatcher.updates_queue.put_nowait(None)

    async with lock:  # Another holder: resolving must not wait for it.
        await asyncio.wait_for(dispatcher.handler_worker(lock), 1)

    assert listener.resolved == [msg]
    assert handled == []


async def test_handler_worker_offers_no_unparsed_update_to_the_listener() -> None:
    dispatcher = make_real_dispatcher()
    listener = FakeListener()
    dispatcher.listeners[type(None)] = listener  # ty: ignore[invalid-assignment]
    dispatcher.update_parsers = {}
    dispatcher.updates_queue.put_nowait((FakeRawUpdate(), {}, {}))
    dispatcher.updates_queue.put_nowait(None)

    await dispatcher.handler_worker(asyncio.Lock())

    assert listener.resolved == []


async def test_handler_worker_passes_unknown_updates_unparsed() -> None:
    dispatcher = make_real_dispatcher()
    packet = (FakeRawUpdate(), {}, {})
    seen: list[tuple[object, ...]] = []

    async def handle_update(packet: object, parsed: object, handler_type: object) -> None:
        seen.append((packet, parsed, handler_type))

    dispatcher.update_parsers = {}
    dispatcher.handle_update = handle_update
    dispatcher.updates_queue.put_nowait(packet)
    dispatcher.updates_queue.put_nowait(None)

    await dispatcher.handler_worker(asyncio.Lock())

    assert seen == [(packet, None, type(None))]


async def test_handler_worker_keeps_running_after_errors(caplog: pytest.LogCaptureFixture) -> None:
    dispatcher = make_real_dispatcher()
    errors = iter([StopPropagation(), RuntimeError("boom"), None])
    handled: list[object] = []

    async def parser(update: object, users: object, chats: object) -> tuple[object, type]:
        if update == "bad-parse":
            msg = "parse"
            raise ValueError(msg)
        return (update, MessageHandler)

    async def handle_update(packet: object, parsed: object, handler_type: object) -> None:
        handled.append(parsed)
        error = next(errors)
        if error is not None:
            raise error

    dispatcher.update_parsers = {str: parser}
    dispatcher.handle_update = handle_update
    for update in ("stop", "boom", "bad-parse", "ok"):
        dispatcher.updates_queue.put_nowait((update, {}, {}))
    dispatcher.updates_queue.put_nowait(None)
    dispatcher.updates_queue.put_nowait(("after-sentinel", {}, {}))

    with caplog.at_level(logging.ERROR, logger="pyroflow.dispatcher"):
        await dispatcher.handler_worker(asyncio.Lock())

    assert handled == ["stop", "boom", "ok"]
    assert caplog.text.count("Unexpected error in handler_worker") == 2
    assert dispatcher.updates_queue.qsize() == 1, "the worker must stop at the sentinel"


# --- listening end to end ----------------------------------------------------


async def test_a_listened_reply_skips_the_handlers_and_the_next_one_reaches_them() -> None:
    dispatcher = make_real_dispatcher()
    listener = MessageListener()
    dispatcher.register_listener(listener)
    calls: list[tuple[object, ...]] = []
    dispatcher.groups[0] = [MessageHandler(recording(calls, "handler"))]
    waiter = asyncio.create_task(listener.listen(100, 7))
    await asyncio.sleep(0)
    reply, later = make_message(100, 7, 5), make_message(100, 7, 6)
    parsed = iter([reply, later])

    async def parser(update: object, users: object, chats: object) -> tuple[object, type]:
        return (next(parsed), MessageHandler)

    dispatcher.update_parsers = {FakeRawUpdate: parser}
    for _ in range(2):
        dispatcher.updates_queue.put_nowait((FakeRawUpdate(), {}, {}))
    dispatcher.updates_queue.put_nowait(None)

    await dispatcher.handler_worker(asyncio.Lock())

    assert await waiter is reply
    assert calls == [("handler", later)]


async def test_listen_inside_a_handler_of_the_same_chat_does_not_deadlock() -> None:
    dispatcher = make_real_dispatcher()
    listener = MessageListener()
    dispatcher.register_listener(listener)
    errors: list[BaseException] = []

    async def asks_again(client: object, update: Message) -> None:
        try:
            await listener.listen(update.chat.id, update.from_user.id, timeout=0.05)
        except BaseException as e:  # noqa: BLE001  # the test records what `listen` raised
            errors.append(e)

    dispatcher.groups[0] = [MessageHandler(asks_again)]

    await asyncio.wait_for(
        dispatcher.handle_update(RAW_PACKET, make_message(100, 7, 5), MessageHandler), 1
    )

    assert len(errors) == 1
    assert isinstance(errors[0], ListenerTimeout)


# --- workers policy: the handler side of a wait ---------------------------


def _waiting_bot(workers: int) -> tuple[pyroflow.Client, MessageListener, list[object]]:
    """A real client whose raw handler waits in `listen` for each `UpdateConfig`.

    The waits are on chats 1, 2, ... in arrival order; any other raw update is
    recorded as `"ping"`, to show a worker still reads the queue.
    """
    client = pyroflow.Client(
        "probe", api_id=1, api_hash="x", in_memory=True, workers=workers, skip_updates=True
    )
    listener = MessageListener()
    client.register_listener(listener)
    results: list[object] = []
    chats = iter(range(1, 100))

    async def handler(client: object, update: object, users: object, chats_: object) -> None:
        if not isinstance(update, UpdateConfig):
            results.append("ping")
            return

        chat = next(chats)
        try:
            await listener.listen(chat, timeout=5)
            results.append((chat, "answered"))
        except Exception as e:  # noqa: BLE001  # the test records how each wait ended
            results.append((chat, type(e)))

    client.add_handler(RawUpdateHandler(handler))
    return client, listener, results


async def _until(condition: Callable[[], bool], timeout: float = 1) -> None:
    async def poll() -> None:
        while not condition():
            await asyncio.sleep(0.005)

    await asyncio.wait_for(poll(), timeout)


async def _start_waits(client: pyroflow.Client, asks: int, *, ping: bool = True) -> None:
    await client.dispatcher.start()
    for _ in range(asks):
        client.dispatcher.updates_queue.put_nowait((UpdateConfig(), {}, {}))
    if ping:
        client.dispatcher.updates_queue.put_nowait((UpdateLoginToken(), {}, {}))


async def test_no_policy_lets_waits_take_every_worker() -> None:
    client, listener, results = _waiting_bot(workers=2)
    await _start_waits(client, 2)
    try:
        await _until(lambda: len(listener.listeners) == 2)
        await asyncio.sleep(0.05)

        assert "ping" not in results  # the bot is frozen: no worker reads the queue
        assert client.dispatcher.handler_waits == {}  # no policy tracks nothing
    finally:
        await asyncio.wait_for(client.dispatcher.stop(), 2)


async def test_policy_reject_refuses_the_wait_that_would_take_the_last_worker() -> None:
    client, listener, results = _waiting_bot(workers=2)
    client.with_workers_policy(WorkersPolicy(WorkersBusyMode.REJECT))
    await _start_waits(client, 2)
    try:
        await _until(lambda: "ping" in results)

        assert (2, ListenerWorkersBusy) in results
        assert list(listener.listeners) == [ListenerKey(1)]
    finally:
        await asyncio.wait_for(client.dispatcher.stop(), 2)


async def test_policy_busy_timeout_lets_a_freed_worker_go_to_the_waiting_one() -> None:
    client, listener, results = _waiting_bot(workers=2)
    client.with_workers_policy(WorkersPolicy(WorkersBusyMode.REJECT, busy_timeout=2))
    await _start_waits(client, 2, ping=False)
    try:
        await _until(lambda: len(listener.listeners) == 1 and len(results) == 0)
        await asyncio.sleep(0.05)  # the second wait now waits for a free worker

        assert await listener.resolve(make_message(1)) is True
        await _until(lambda: ListenerKey(2) in listener.listeners)

        assert results == [(1, "answered")]
        assert len(client.dispatcher.handler_waits) == 1
    finally:
        await asyncio.wait_for(client.dispatcher.stop(), 2)


async def test_stop_ends_a_wait_held_by_a_busy_timeout() -> None:
    client, listener, results = _waiting_bot(workers=2)
    client.with_workers_policy(WorkersPolicy(WorkersBusyMode.REJECT, busy_timeout=30))
    await _start_waits(client, 2, ping=False)
    await _until(lambda: len(listener.listeners) == 1)
    await asyncio.sleep(0.05)  # the second wait now waits for a free worker

    await asyncio.wait_for(client.dispatcher.stop(), 2)

    assert sorted(results, key=str) == [(1, ListenerCancelled), (2, ListenerCancelled)]
    assert client.dispatcher.handler_waits == {}


async def test_policy_cancel_oldest_evicts_the_oldest_wait() -> None:
    client, listener, results = _waiting_bot(workers=2)
    client.with_workers_policy(WorkersPolicy(WorkersBusyMode.CANCEL_OLDEST))
    await _start_waits(client, 2)
    try:
        await _until(
            lambda: (1, ListenerEvicted) in results and ListenerKey(2) in listener.listeners
        )

        waits = client.dispatcher.handler_waits.values()
        assert [model.key for _, model in waits] == [ListenerKey(2)]
    finally:
        await asyncio.wait_for(client.dispatcher.stop(), 2)


async def test_policy_cancel_oldest_without_a_wait_to_evict_refuses() -> None:
    client, _, results = _waiting_bot(workers=1)
    client.with_workers_policy(WorkersPolicy(WorkersBusyMode.CANCEL_OLDEST))
    await _start_waits(client, 1)
    try:
        await _until(lambda: "ping" in results)

        assert results[0] == (1, ListenerWorkersBusy)
    finally:
        await asyncio.wait_for(client.dispatcher.stop(), 2)


async def test_init_starts_with_no_policy_and_no_waits() -> None:
    dispatcher = make_real_dispatcher()

    assert dispatcher.workers_policy is None
    assert dispatcher.handler_waits == {}
    assert dispatcher.worker_freed is None


def _hold_a_worker(dispatcher: Dispatcher, chat_id: int = 1) -> asyncio.Future:
    """Track a wait as `UpdateListener.listen` does, and return its future."""
    listener = MessageListener()
    future = asyncio.get_running_loop().create_future()
    model = ListenerModel(ListenerKey(chat_id), future)
    listener.listeners[model.key] = model
    dispatcher.handler_waits[future] = (listener, model)
    return future


async def test_lacks_free_workers_counts_the_holding_waits() -> None:
    dispatcher = make_real_dispatcher(workers=2)
    policy = WorkersPolicy(WorkersBusyMode.REJECT, free_workers=1)

    assert dispatcher.lacks_free_workers(policy) is False
    _hold_a_worker(dispatcher)
    assert dispatcher.lacks_free_workers(policy) is True


async def test_enter_handler_wait_with_workers_free_leaves_the_waits_alone() -> None:
    dispatcher = make_real_dispatcher(workers=3)
    policy = WorkersPolicy(WorkersBusyMode.CANCEL_OLDEST, free_workers=1)
    future = _hold_a_worker(dispatcher)

    await dispatcher.enter_handler_wait(policy, ListenerKey(2))

    assert list(dispatcher.handler_waits) == [future]
    assert not future.done()


async def test_enter_handler_wait_with_reject_raises_and_keeps_the_waits() -> None:
    dispatcher = make_real_dispatcher(workers=2)
    policy = WorkersPolicy(WorkersBusyMode.REJECT, free_workers=1)
    future = _hold_a_worker(dispatcher)

    with pytest.raises(ListenerWorkersBusy):
        await dispatcher.enter_handler_wait(policy, ListenerKey(2))

    assert list(dispatcher.handler_waits) == [future]


async def test_enter_handler_wait_steps_in_once_the_busy_timeout_expires() -> None:
    dispatcher = make_real_dispatcher(workers=2)
    policy = WorkersPolicy(WorkersBusyMode.REJECT, free_workers=1, busy_timeout=0.01)
    _hold_a_worker(dispatcher)

    with pytest.raises(ListenerWorkersBusy):
        await dispatcher.enter_handler_wait(policy, ListenerKey(2))


async def test_enter_handler_wait_with_cancel_oldest_evicts_only_the_oldest() -> None:
    dispatcher = make_real_dispatcher(workers=3)
    policy = WorkersPolicy(WorkersBusyMode.CANCEL_OLDEST, free_workers=1)
    oldest, newer = _hold_a_worker(dispatcher, 1), _hold_a_worker(dispatcher, 2)

    await dispatcher.enter_handler_wait(policy, ListenerKey(3))

    assert isinstance(oldest.exception(), ListenerEvicted)
    assert list(dispatcher.handler_waits) == [newer]
    assert not newer.done()


async def test_wait_for_free_worker_gives_up_at_the_timeout() -> None:
    dispatcher = make_real_dispatcher(workers=1)
    policy = WorkersPolicy(WorkersBusyMode.REJECT, busy_timeout=0.05)
    loop = asyncio.get_running_loop()
    start = loop.time()

    await asyncio.wait_for(dispatcher.wait_for_free_worker(policy), 1)

    assert loop.time() - start >= 0.04
    assert isinstance(dispatcher.worker_freed, asyncio.Event)


async def test_wait_for_free_worker_returns_once_a_wait_ends() -> None:
    dispatcher = make_real_dispatcher(workers=2)
    policy = WorkersPolicy(WorkersBusyMode.REJECT, busy_timeout=5)
    future = _hold_a_worker(dispatcher)
    task = asyncio.ensure_future(dispatcher.wait_for_free_worker(policy))
    await asyncio.sleep(0.01)

    dispatcher.end_handler_wait(future)

    await asyncio.wait_for(task, 1)


async def test_end_handler_wait_frees_the_slot_and_wakes_waiters() -> None:
    dispatcher = make_real_dispatcher()
    future = _hold_a_worker(dispatcher)
    dispatcher.worker_freed = asyncio.Event()
    woken = asyncio.ensure_future(dispatcher.worker_freed.wait())
    await asyncio.sleep(0)

    dispatcher.end_handler_wait(future)

    assert dispatcher.handler_waits == {}
    assert await asyncio.wait_for(woken, 1) is True
    assert dispatcher.worker_freed.is_set() is False


async def test_end_handler_wait_of_an_untracked_wait_wakes_nobody() -> None:
    dispatcher = make_real_dispatcher()
    dispatcher.worker_freed = asyncio.Event()
    woken = asyncio.ensure_future(dispatcher.worker_freed.wait())
    await asyncio.sleep(0)

    dispatcher.end_handler_wait(asyncio.get_running_loop().create_future())
    await asyncio.sleep(0)

    assert not woken.done()
    woken.cancel()


async def test_end_handler_wait_without_a_timed_wait_makes_no_event() -> None:
    dispatcher = make_real_dispatcher()

    dispatcher.end_handler_wait(_hold_a_worker(dispatcher))

    assert dispatcher.worker_freed is None


async def test_handler_worker_marks_the_worker_for_listen_and_clears_it_after() -> None:
    dispatcher = make_real_dispatcher()
    seen: list[object] = []

    async def handle_update(packet: object, parsed: object, handler_type: object) -> None:
        seen.append(handler_worker_var.get())

    dispatcher.handle_update = handle_update
    dispatcher.update_parsers = {}
    dispatcher.updates_queue.put_nowait(("raw", {}, {}))
    dispatcher.updates_queue.put_nowait(None)

    await dispatcher.handler_worker(asyncio.Lock())

    assert seen == [(dispatcher, asyncio.current_task())]
    assert handler_worker_var.get() is None
