"""Dispatcher: listener registry, lifecycle, and the route of an update.

Each update goes to the listener of its type first; one it takes stops
there, any other runs through the handler groups as in Pyrogram.
"""

from __future__ import annotations as _annotations

import asyncio
import logging
import random
from contextlib import asynccontextmanager
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any

import pytest

from pyrogram import ContinuePropagation, StopPropagation, filters
from pyrogram.handlers import (
    CallbackQueryHandler,
    ErrorHandler,
    MessageHandler,
    RawUpdateHandler,
)
from pyrogram.raw.types import UpdateConfig, UpdateLoginToken
from pyrogram.types import Message

import pyroflow
from pyroflow.dispatcher import dispatcher as dispatcher_module
from pyroflow.dispatcher.dispatcher import _HANDLER_WORKER, _HANDLER_HOLD, Dispatcher
from pyroflow.enums import DuplicatePolicy, WorkersPolicy
from pyroflow.errors import (
    ListenerAlreadyExists,
    ListenerCancelled,
    ListenerError,
    ListenerEvicted,
    ListenerReplaced,
    ListenerTimeout,
    ListenerWorkersBusy,
)
from pyroflow.models import CallbackQueryKey, ListenerModel, MessageKey
from pyroflow.update_listener import CallbackQueryListener, MessageListener

from ..conftest import make_callback_query, make_message

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Awaitable, Callable


# --- module-level definitions ----------------------------------------------


def test_module_logger_is_named_after_the_module() -> None:
    assert dispatcher_module.log.name == "pyroflow.dispatcher.dispatcher"


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
    waiter = asyncio.create_task(listener.listen(MessageKey(chat_id=100, user_id=7)))
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

    with caplog.at_level(logging.ERROR, logger="pyroflow.dispatcher.dispatcher"):
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

    with caplog.at_level(logging.ERROR, logger="pyroflow.dispatcher.dispatcher"):
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


async def test_raw_handler_whose_check_fails_is_skipped() -> None:
    dispatcher = make_real_dispatcher()
    calls: list[tuple[object, ...]] = []
    msg = make_message()
    raw = RawUpdateHandler(recording(calls, "raw"))

    async def check(client: object, update: object) -> bool:
        return False

    raw.check = check
    dispatcher.groups[0] = [raw, MessageHandler(recording(calls, "next"))]

    assert await dispatcher.handle_update(RAW_PACKET, msg, MessageHandler) is None
    assert calls == [("next", msg)]


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

    with caplog.at_level(logging.ERROR, logger="pyroflow.dispatcher.dispatcher"):
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


async def test_handler_worker_parses_and_dispatches() -> None:
    dispatcher = make_real_dispatcher()
    packet = (FakeRawUpdate(), {}, {})
    seen: list[tuple[object, ...]] = []

    async def parser(update: object, users: object, chats: object) -> tuple[object, type]:
        return ("parsed", MessageHandler)

    async def handle_update(packet: object, parsed: object, handler_type: object) -> None:
        seen.append((packet, parsed, handler_type))

    dispatcher.update_parsers = {FakeRawUpdate: parser}
    dispatcher.handle_update = handle_update
    dispatcher.updates_queue.put_nowait(packet)
    dispatcher.updates_queue.put_nowait(None)

    await dispatcher.handler_worker()

    assert seen == [(packet, "parsed", MessageHandler)]


async def test_handler_worker_resolves_a_listened_update_before_the_handlers() -> None:
    dispatcher = make_real_dispatcher()
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

    await asyncio.wait_for(dispatcher.handler_worker(), 1)

    assert listener.resolved == [msg]
    assert handled == []


async def test_handler_worker_offers_no_unparsed_update_to_the_listener() -> None:
    dispatcher = make_real_dispatcher()
    listener = FakeListener()
    dispatcher.listeners[type(None)] = listener  # ty: ignore[invalid-assignment]
    dispatcher.update_parsers = {}
    dispatcher.updates_queue.put_nowait((FakeRawUpdate(), {}, {}))
    dispatcher.updates_queue.put_nowait(None)

    await dispatcher.handler_worker()

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

    await dispatcher.handler_worker()

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

    with caplog.at_level(logging.ERROR, logger="pyroflow.dispatcher.dispatcher"):
        await dispatcher.handler_worker()

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
    waiter = asyncio.create_task(listener.listen(MessageKey(chat_id=100, user_id=7)))
    await asyncio.sleep(0)
    reply, later = make_message(100, 7, 5), make_message(100, 7, 6)
    parsed = iter([reply, later])

    async def parser(update: object, users: object, chats: object) -> tuple[object, type]:
        return (next(parsed), MessageHandler)

    dispatcher.update_parsers = {FakeRawUpdate: parser}
    for _ in range(2):
        dispatcher.updates_queue.put_nowait((FakeRawUpdate(), {}, {}))
    dispatcher.updates_queue.put_nowait(None)

    await dispatcher.handler_worker()

    assert await waiter is reply
    assert calls == [("handler", later)]


async def test_listen_inside_a_handler_of_the_same_chat_does_not_deadlock() -> None:
    dispatcher = make_real_dispatcher()
    listener = MessageListener()
    dispatcher.register_listener(listener)
    errors: list[BaseException] = []

    async def asks_again(client: object, update: Message) -> None:
        try:
            await listener.listen(
                MessageKey(chat_id=update.chat.id, user_id=update.from_user.id), timeout=0.05
            )
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
            await listener.listen(MessageKey(chat_id=chat), timeout=5)
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
        assert client.dispatcher.listener_waits == {}  # no policy tracks nothing
    finally:
        await asyncio.wait_for(client.dispatcher.stop(), 2)


async def test_policy_reject_refuses_the_wait_that_would_take_the_last_worker() -> None:
    client, listener, results = _waiting_bot(workers=2)
    client.setup_pyroflow(workers_policy=WorkersPolicy.REJECT)
    await _start_waits(client, 2)
    try:
        await _until(lambda: "ping" in results)

        assert (2, ListenerWorkersBusy) in results
        assert list(listener.listeners) == [MessageKey(1)]
    finally:
        await asyncio.wait_for(client.dispatcher.stop(), 2)


async def test_policy_cancel_oldest_evicts_the_oldest_wait() -> None:
    client, listener, results = _waiting_bot(workers=2)
    client.setup_pyroflow(workers_policy=WorkersPolicy.CANCEL_OLDEST)
    await _start_waits(client, 2)
    try:
        await _until(
            lambda: (1, ListenerEvicted) in results and MessageKey(2) in listener.listeners
        )

        waits = client.dispatcher.listener_waits
        assert [model.key for model in waits] == [MessageKey(2)]
    finally:
        await asyncio.wait_for(client.dispatcher.stop(), 2)


def _stubborn_bot(
    workers: int,
) -> tuple[pyroflow.Client, MessageListener, list[object], asyncio.Event]:
    """Like `_waiting_bot`, but an evicted handler goes on working until the event is set."""
    client = pyroflow.Client(
        "probe", api_id=1, api_hash="x", in_memory=True, workers=workers, skip_updates=True
    )
    client.setup_pyroflow(workers_policy=WorkersPolicy.CANCEL_OLDEST)
    listener = MessageListener()
    client.register_listener(listener)
    results: list[object] = []
    finish = asyncio.Event()
    chats = iter(range(1, 100))

    async def handler(client: object, update: object, users: object, chats_: object) -> None:
        chat = next(chats)
        try:
            await listener.listen(MessageKey(chat_id=chat), timeout=5)
        except ListenerEvicted:
            results.append((chat, "evicted"))
            await finish.wait()
        except Exception as e:  # noqa: BLE001  # the test records how each wait ended
            results.append((chat, type(e)))

    client.add_handler(RawUpdateHandler(handler))
    return client, listener, results, finish


async def test_policy_cancel_oldest_starts_the_new_wait_while_the_evicted_handler_works() -> None:
    client, listener, results, finish = _stubborn_bot(workers=2)
    await _start_waits(client, 2, ping=False)
    try:
        await _until(lambda: (1, "evicted") in results)

        assert MessageKey(2) in listener.listeners
        assert len(client.dispatcher.listener_waits) == 1
    finally:
        finish.set()
        await asyncio.wait_for(client.dispatcher.stop(), 2)


async def test_an_evicted_handler_that_waits_again_evicts_the_next_oldest() -> None:
    client = pyroflow.Client(
        "probe", api_id=1, api_hash="x", in_memory=True, workers=3, skip_updates=True
    )
    client.setup_pyroflow(workers_policy=WorkersPolicy.CANCEL_OLDEST)
    listener = MessageListener()
    client.register_listener(listener)
    results: list[object] = []
    chats = iter(range(1, 100))

    async def handler(client: object, update: object, users: object, chats_: object) -> None:
        chat = next(chats)
        try:
            try:
                await listener.listen(MessageKey(chat_id=chat), timeout=5)
            except ListenerEvicted:
                await listener.listen(MessageKey(chat_id=chat + 10), timeout=5)
        except Exception as e:  # noqa: BLE001  # the test records how each wait ended
            results.append((chat, type(e)))

    client.add_handler(RawUpdateHandler(handler))
    await _start_waits(client, 3, ping=False)
    try:
        await _until(lambda: (1, ListenerEvicted) in results)

        waits = client.dispatcher.listener_waits
        assert [model.key for model in waits] == [MessageKey(12), MessageKey(13)]
    finally:
        await asyncio.wait_for(client.dispatcher.stop(), 2)


async def test_policy_cancel_oldest_without_a_wait_to_evict_refuses() -> None:
    client, _, results = _waiting_bot(workers=1)
    client.setup_pyroflow(workers_policy=WorkersPolicy.CANCEL_OLDEST)
    await _start_waits(client, 1)
    try:
        await _until(lambda: "ping" in results)

        assert results[0] == (1, ListenerWorkersBusy)
    finally:
        await asyncio.wait_for(client.dispatcher.stop(), 2)


async def test_init_starts_with_no_waits() -> None:
    dispatcher = make_real_dispatcher()

    assert dispatcher.listener_waits == {}
    assert dispatcher.handler_worker_tasks == []


async def _started_dispatcher(workers: int) -> Dispatcher:
    """A started dispatcher that counts `workers` running, which `make_client` does not run."""
    dispatcher = make_real_dispatcher(workers=workers)
    await dispatcher.start()
    loop = asyncio.get_running_loop()
    dispatcher.handler_worker_tasks.extend(loop.create_future() for _ in range(workers))
    return dispatcher


async def test_a_restart_keeping_the_handlers_counts_only_the_new_workers() -> None:
    dispatcher = make_real_dispatcher(workers=2)
    dispatcher.client.no_updates = False
    await dispatcher.start()
    await dispatcher.stop(clear_handlers=False)

    await dispatcher.start()
    dispatcher.listener_waits[
        ListenerModel(MessageKey(100, 7), asyncio.get_running_loop().create_future())
    ] = MessageListener()

    try:
        # Two workers leave one slot, which the wait above takes; those of the last run left the list.
        with pytest.raises(ListenerWorkersBusy):
            dispatcher.enter_handler_wait(WorkersPolicy.REJECT, MessageKey(100, 8))
    finally:
        dispatcher.listener_waits.clear()
        await dispatcher.stop()


async def test_every_worker_counts_itself_before_any_takes_an_update() -> None:
    dispatcher = make_real_dispatcher(workers=3)
    dispatcher.client.no_updates = False
    seen: list[int] = []

    async def parser(update: object, users: object, chats: object) -> tuple[None, type]:
        seen.append(len(dispatcher.handler_worker_tasks))
        return None, type(None)

    dispatcher.update_parsers = {FakeRawUpdate: parser}

    await dispatcher.start()
    try:
        # Queued before any worker runs; `start` drops what comes before it.
        dispatcher.enqueue(FakeRawUpdate(), users={}, chats={})  # ty: ignore[invalid-argument-type]
        await _until(lambda: seen != [])
    finally:
        await dispatcher.stop()

    assert seen == [3]


@pytest.mark.parametrize("mode", list(WorkersPolicy))
@pytest.mark.parametrize("workers", [1, 0])
async def test_enter_handler_wait_with_no_worker_to_spare_refuses(
    mode: WorkersPolicy, workers: int
) -> None:
    dispatcher = await _started_dispatcher(workers=workers)

    with pytest.raises(ListenerWorkersBusy):
        dispatcher.enter_handler_wait(mode, MessageKey(1))


def _hold_a_worker(dispatcher: Dispatcher, chat_id: int = 1) -> ListenerModel:
    """Take a slot and track a wait as `UpdateListener.listen` does, and return its model."""
    listener = MessageListener()
    model = ListenerModel(MessageKey(chat_id), asyncio.get_running_loop().create_future())
    listener._add(model)
    model.add_done_callback(dispatcher.end_handler_wait)
    dispatcher.listener_waits[model] = listener
    return model


async def test_enter_handler_wait_with_workers_free_leaves_the_waits_alone() -> None:
    dispatcher = await _started_dispatcher(workers=3)
    policy = WorkersPolicy.CANCEL_OLDEST
    model = _hold_a_worker(dispatcher)

    dispatcher.enter_handler_wait(policy, MessageKey(2))

    assert list(dispatcher.listener_waits) == [model]
    assert not model.done()


async def test_enter_handler_wait_with_reject_raises_and_keeps_the_waits() -> None:
    dispatcher = await _started_dispatcher(workers=2)
    policy = WorkersPolicy.REJECT
    model = _hold_a_worker(dispatcher)

    with pytest.raises(ListenerWorkersBusy):
        dispatcher.enter_handler_wait(policy, MessageKey(2))

    assert list(dispatcher.listener_waits) == [model]


async def test_enter_handler_wait_with_cancel_oldest_evicts_only_the_oldest() -> None:
    dispatcher = await _started_dispatcher(workers=3)
    oldest, newer = _hold_a_worker(dispatcher, 1), _hold_a_worker(dispatcher, 2)

    dispatcher.enter_handler_wait(WorkersPolicy.CANCEL_OLDEST, MessageKey(3))

    assert isinstance(oldest.future.exception(), ListenerEvicted)
    assert not newer.done()
    assert list(dispatcher.listener_waits) == [newer]


async def test_enter_handler_wait_evicts_each_wait_once() -> None:
    dispatcher = await _started_dispatcher(workers=3)
    oldest, newer = _hold_a_worker(dispatcher, 1), _hold_a_worker(dispatcher, 2)

    # The first evicted wait left at once, though its `listen` has not reached `finally`.
    dispatcher.enter_handler_wait(WorkersPolicy.CANCEL_OLDEST, MessageKey(3))
    _hold_a_worker(dispatcher, 3)
    dispatcher.enter_handler_wait(WorkersPolicy.CANCEL_OLDEST, MessageKey(4))

    assert isinstance(oldest.future.exception(), ListenerEvicted)
    assert isinstance(newer.future.exception(), ListenerEvicted)


@pytest.mark.parametrize("mode", list(WorkersPolicy))
async def test_enter_handler_wait_takes_the_slot_of_a_wait_that_just_ended(
    mode: WorkersPolicy,
) -> None:
    dispatcher = await _started_dispatcher(workers=3)
    ended, pending = _hold_a_worker(dispatcher, 1), _hold_a_worker(dispatcher, 2)
    dispatcher.listener_waits[ended]._remove(ended.key)
    ended.resolve("update")

    dispatcher.enter_handler_wait(mode, MessageKey(3))

    assert ended.future.result() == "update"
    assert not pending.done()
    assert list(dispatcher.listener_waits) == [pending]


async def test_enter_handler_wait_with_cancel_oldest_takes_the_slot_of_a_cancelled_task() -> None:
    dispatcher = await _started_dispatcher(workers=2)
    model = _hold_a_worker(dispatcher)
    listener = dispatcher.listener_waits[model]
    model.future.cancel()  # as a cancelled task does: no done callback, and `finally` not reached yet

    dispatcher.enter_handler_wait(WorkersPolicy.CANCEL_OLDEST, MessageKey(2))

    assert dispatcher.listener_waits == {}
    assert listener.listeners == {}


async def test_enter_handler_wait_with_a_free_slot_lets_it_through() -> None:
    dispatcher = await _started_dispatcher(workers=2)

    dispatcher.enter_handler_wait(WorkersPolicy.REJECT, MessageKey(1))

    assert dispatcher.listener_waits == {}


async def test_end_handler_wait_frees_the_slot() -> None:
    dispatcher = await _started_dispatcher(workers=2)
    model = _hold_a_worker(dispatcher)

    dispatcher.end_handler_wait(model)

    assert dispatcher.listener_waits == {}


async def test_end_handler_wait_of_an_untracked_wait_does_nothing() -> None:
    dispatcher = await _started_dispatcher(workers=2)
    model = _hold_a_worker(dispatcher)
    dispatcher.end_handler_wait(model)

    dispatcher.end_handler_wait(model)

    assert dispatcher.listener_waits == {}


async def test_a_wait_replacing_one_takes_its_slot_with_no_slot_free() -> None:
    dispatcher = await _started_dispatcher(workers=2)
    dispatcher.client.workers_policy = WorkersPolicy.REJECT
    listener = MessageListener()

    async def wait() -> object:
        token = _HANDLER_WORKER.set((dispatcher, asyncio.current_task()))
        try:
            return await listener.listen(MessageKey(chat_id=1))
        finally:
            _HANDLER_WORKER.reset(token)

    first = asyncio.ensure_future(wait())
    await asyncio.sleep(0.01)
    second = asyncio.ensure_future(wait())
    await asyncio.sleep(0.01)

    with pytest.raises(ListenerReplaced):
        await first

    assert len(dispatcher.listener_waits) == 1

    listener.cancel(MessageKey(1))

    with pytest.raises(ListenerCancelled):
        await second

    assert dispatcher.listener_waits == {}


async def test_a_wait_replacing_one_that_holds_no_slot_is_refused_with_no_slot_free() -> None:
    dispatcher = await _started_dispatcher(workers=2)
    dispatcher.client.workers_policy = WorkersPolicy.REJECT
    listener = MessageListener()
    _hold_a_worker(dispatcher, 9)
    old = asyncio.ensure_future(
        listener.listen(MessageKey(chat_id=1))
    )  # outside a worker, so it holds no slot
    await asyncio.sleep(0)

    with pytest.raises(ListenerWorkersBusy):
        await _on_a_worker(dispatcher, lambda: listener.listen(MessageKey(chat_id=1)))

    assert not old.done()

    listener.cancel(MessageKey(1))

    with pytest.raises(ListenerCancelled):
        await old


def test_handler_worker_context_is_unset_outside_a_worker_and_named_after_the_library() -> None:
    assert _HANDLER_WORKER.get() is None
    assert _HANDLER_WORKER.name == "pyroflow_handler_worker"


def test_handler_worker_context_stays_out_of_the_public_names() -> None:
    assert "_HANDLER_WORKER" not in dispatcher_module.__all__
    assert not hasattr(pyroflow, "_HANDLER_WORKER")


async def test_handler_worker_marks_the_worker_for_listen_and_clears_it_after() -> None:
    dispatcher = make_real_dispatcher()
    seen: list[object] = []

    async def handle_update(packet: object, parsed: object, handler_type: object) -> None:
        seen.append(_HANDLER_WORKER.get())

    dispatcher.handle_update = handle_update
    dispatcher.update_parsers = {}
    dispatcher.updates_queue.put_nowait(("raw", {}, {}))
    dispatcher.updates_queue.put_nowait(None)

    await dispatcher.handler_worker()

    assert seen == [(dispatcher, asyncio.current_task())]
    assert _HANDLER_WORKER.get() is None


# --- stress: the waits, their slots and the workers -------------------------

STRESS_SEEDS = range(5)


class _Script:
    """A raw update whose handler awaits `script`, on a real worker."""

    def __init__(self, script: Callable[[], Awaitable[None]]) -> None:
        self.script = script


class _Reply:
    """A raw update the worker parses to `parsed`, so a reply takes the real path."""

    def __init__(self, parsed: object, handler_type: type) -> None:
        self.parsed = parsed
        self.handler_type = handler_type


class _RecordedWaits(dict):
    """`listener_waits` that remembers the most slots held at once, so no moment escapes the check."""

    most = 0

    def __setitem__(self, key: object, value: object) -> None:
        super().__setitem__(key, value)
        self.most = max(self.most, len(self))


class _Bot:
    """A real client with real workers, driven through its update queue."""

    def __init__(self, workers: int, policy: WorkersPolicy, **listener_kw: Any) -> None:
        self.workers = workers
        self.client = pyroflow.Client(
            "probe", api_id=1, api_hash="x", in_memory=True, workers=workers, skip_updates=True
        )
        self.client.setup_pyroflow(workers_policy=policy)
        self.listener = MessageListener(**listener_kw)
        self.client.register_listener(self.listener)
        self.dispatcher = self.client.dispatcher
        self.dispatcher.listener_waits = _RecordedWaits()
        self.dispatcher.update_parsers[_Reply] = self.parse
        self.client.add_handler(RawUpdateHandler(self.handle))
        self.outcomes: list[tuple[int, object]] = []
        self.unclaimed: list[object] = []
        self.failures: list[Exception] = []
        self.scripts_sent = 0
        self.scripts_done = 0

    @staticmethod
    async def parse(update: _Reply, users: object, chats: object) -> tuple[object, type]:
        return update.parsed, update.handler_type

    async def handle(self, client: object, update: object, users: object, chats: object) -> None:
        if isinstance(update, _Reply):
            self.unclaimed.append(update.parsed)
        elif isinstance(update, _Script):
            try:
                await update.script()
            except Exception as e:  # noqa: BLE001  # any such error fails the test on exit
                self.failures.append(e)
            finally:
                self.scripts_done += 1

    def send(self, update: object) -> None:
        self.dispatcher.updates_queue.put_nowait((update, {}, {}))

    def run(self, script: Callable[[], Awaitable[None]]) -> None:
        self.scripts_sent += 1
        self.send(_Script(script))

    def reply(self, parsed: object, handler_type: type = MessageHandler) -> None:
        self.send(_Reply(parsed, handler_type))

    def wait_on(self, chat_id: int, user_id: int | None = None, timeout: float = 5) -> None:
        async def script() -> None:
            outcome: object
            try:
                outcome = await self.listener.listen(
                    MessageKey(chat_id=chat_id, user_id=user_id), timeout=timeout
                )
            except ListenerError as e:
                outcome = type(e)
            self.outcomes.append((chat_id, outcome))

        self.run(script)

    async def settle(self) -> None:
        """Wait until every script ended and every update in the queue was taken."""
        await _until(
            lambda: (
                self.scripts_done == self.scripts_sent and self.dispatcher.updates_queue.empty()
            ),
            3,
        )
        await asyncio.sleep(0.01)

    def assert_every_slot_is_free(self) -> None:
        assert self.dispatcher.listener_waits == {}


@asynccontextmanager
async def _running(bot: _Bot) -> AsyncIterator[_Bot]:
    await bot.dispatcher.start()
    try:
        yield bot
        assert bot.failures == []
        assert bot.dispatcher.listener_waits.most <= bot.workers - 1
    finally:
        await asyncio.wait_for(bot.dispatcher.stop(), 5)


def _on_a_worker(dispatcher: Dispatcher, script: Callable[[], Awaitable[object]]) -> asyncio.Task:
    """Run `script` as a worker of `dispatcher`, to reach more waits at once than real workers."""

    async def run() -> object:
        token = _HANDLER_WORKER.set((dispatcher, asyncio.current_task()))
        try:
            return await script()
        finally:
            _HANDLER_WORKER.reset(token)

    return asyncio.ensure_future(run())


@pytest.mark.parametrize("seed", STRESS_SEEDS)
async def test_stress_each_reply_reaches_only_its_own_wait(seed: int) -> None:
    rng = random.Random(seed)
    keys = [(chat, user) for chat in (1, 2, 3) for user in (7, 8)]
    bot = _Bot(len(keys) + 1, WorkersPolicy.REJECT)

    async with _running(bot):
        got: dict[tuple[int, int], object] = {}

        def wait_for_reply(key: tuple[int, int]) -> None:
            async def script() -> None:
                got[key] = await bot.listener.listen(
                    MessageKey(chat_id=key[0], user_id=key[1]), timeout=5
                )

            bot.run(script)

        for key in keys:
            wait_for_reply(key)

        await _until(lambda: len(bot.listener.listeners) == len(keys))

        replies = {key: make_message(*key, message_id=i) for i, key in enumerate(keys, 1)}
        strangers = [make_message(chat, 99, message_id=50 + chat) for chat in (1, 2, 3)]
        traffic = [*replies.values(), *strangers]
        rng.shuffle(traffic)

        for update in traffic:
            bot.reply(update)

        await bot.settle()

        assert got == replies
        assert sorted(m.id for m in bot.unclaimed) == sorted(m.id for m in strangers)
        bot.assert_every_slot_is_free()


@pytest.mark.parametrize("mode", list(WorkersPolicy))
async def test_stress_the_waits_never_take_the_last_worker(mode: WorkersPolicy) -> None:
    bot = _Bot(4, mode)

    async with _running(bot):
        read = 0

        async def ping() -> None:
            nonlocal read
            read += 1

        for chat in range(1, 31):
            bot.wait_on(chat, timeout=0.3)
            bot.run(ping)

        # Every ping is read while the waits stay open, by the one worker they cannot take.
        await _until(lambda: read == 30)

        assert len(bot.dispatcher.listener_waits) == 3

        await bot.settle()
        bot.assert_every_slot_is_free()


async def test_stress_cancel_oldest_evicts_strictly_oldest_first() -> None:
    bot = _Bot(4, WorkersPolicy.CANCEL_OLDEST)

    async with _running(bot):
        for chat in range(1, 13):
            bot.wait_on(chat)
            await _until(lambda chat=chat: MessageKey(chat) in bot.listener.listeners)

        await _until(lambda: len(bot.outcomes) == 9)

        assert bot.outcomes == [(chat, ListenerEvicted) for chat in range(1, 10)]

        answers = {chat: make_message(chat, message_id=chat) for chat in (10, 11, 12)}
        for answer in answers.values():
            bot.reply(answer)

        await bot.settle()

        assert dict(bot.outcomes[9:]) == answers
        bot.assert_every_slot_is_free()


@pytest.mark.parametrize("mode", list(WorkersPolicy))
async def test_stress_a_chain_of_replacements_keeps_one_wait_and_one_slot(
    mode: WorkersPolicy,
) -> None:
    bot = _Bot(4, mode)

    async with _running(bot):
        # Two other waits, so the key's own slot is the last one and no slot is ever free.
        bot.wait_on(100)
        bot.wait_on(200)
        await _until(lambda: len(bot.dispatcher.listener_waits) == 2)

        for _ in range(10):
            bot.wait_on(1)
            await _until(lambda: len(bot.dispatcher.listener_waits) == 3)

        await _until(lambda: len(bot.outcomes) == 9)

        assert bot.outcomes == [(1, ListenerReplaced)] * 9

        answer = make_message(1)
        bot.reply(answer)
        bot.reply(make_message(100))
        bot.reply(make_message(200))
        await bot.settle()

        assert (1, answer) in bot.outcomes
        bot.assert_every_slot_is_free()


@pytest.mark.parametrize(
    ("duplicates", "lost"),
    [
        (DuplicatePolicy.REJECT, ListenerAlreadyExists),
        (DuplicatePolicy.REPLACE, ListenerCancelled),
    ],
)
async def test_stress_waits_racing_for_one_key_leave_one_owner(
    duplicates: DuplicatePolicy, lost: type[Exception]
) -> None:
    dispatcher = await _started_dispatcher(workers=3)
    dispatcher.client.workers_policy = WorkersPolicy.CANCEL_OLDEST
    listener = MessageListener(duplicate_policy=duplicates)
    owner = _on_a_worker(dispatcher, lambda: listener.listen(MessageKey(chat_id=1)))
    await asyncio.sleep(0.01)

    racing = [
        _on_a_worker(dispatcher, lambda: listener.listen(MessageKey(chat_id=1))) for _ in range(6)
    ]
    tasks = [owner, *racing]

    await _until(lambda: sum(not task.done() for task in tasks) == 1)

    assert list(listener.listeners) == [MessageKey(1)]
    assert len(dispatcher.listener_waits) == 1

    listener.cancel(MessageKey(1))
    outcomes = await asyncio.gather(*tasks, return_exceptions=True)

    assert sum(isinstance(e, lost) for e in outcomes) >= 6
    assert all(isinstance(e, ListenerError) for e in outcomes)
    assert dispatcher.listener_waits == {}


async def test_stress_cancelling_the_task_of_a_wait_frees_its_slot() -> None:
    dispatcher = await _started_dispatcher(workers=3)
    dispatcher.client.workers_policy = WorkersPolicy.REJECT
    listener = MessageListener()
    holders = [
        _on_a_worker(dispatcher, lambda c=c: listener.listen(MessageKey(chat_id=c))) for c in (1, 2)
    ]
    await asyncio.sleep(0.01)

    holders[0].cancel()
    await asyncio.sleep(0.01)

    late = _on_a_worker(dispatcher, lambda: listener.listen(MessageKey(chat_id=3)))
    await asyncio.sleep(0.01)

    assert MessageKey(3) in listener.listeners

    for key in list(listener.listeners):
        listener.cancel(key)

    await asyncio.gather(*holders, late, return_exceptions=True)

    assert dispatcher.listener_waits == {}
    assert listener.listeners == {}


@pytest.mark.parametrize("seed", STRESS_SEEDS)
@pytest.mark.parametrize("mode", list(WorkersPolicy))
@pytest.mark.parametrize("duplicates", list(DuplicatePolicy))
async def test_stress_random_traffic_keeps_every_guarantee(
    seed: int, mode: WorkersPolicy, duplicates: DuplicatePolicy
) -> None:
    rng = random.Random(seed)
    bot = _Bot(3, mode, duplicate_policy=duplicates)
    keys = [(chat, user) for chat in (1, 2) for user in (7, 8)]
    delivered: list[tuple[tuple[int, int], Message]] = []

    def wait(key: tuple[int, int]) -> None:
        async def script() -> None:
            for _ in range(rng.randrange(1, 3)):
                try:
                    update = await bot.listener.listen(
                        MessageKey(chat_id=key[0], user_id=key[1]), timeout=rng.uniform(0.001, 0.01)
                    )
                except ListenerError:
                    continue
                delivered.append((key, update))

        bot.run(script)

    async with _running(bot):
        for number in range(200):
            roll = rng.random()
            key = rng.choice(keys)

            if roll < 0.45:
                wait(key)
            elif roll < 0.8:
                bot.reply(make_message(*key, message_id=number))
            elif roll < 0.9:
                bot.listener.cancel(MessageKey(*key))

            for _ in range(rng.randrange(3)):
                await asyncio.sleep(0)

        await bot.settle()

        assert all((m.chat.id, m.from_user.id) == key for key, m in delivered)
        assert len({m.id for _, m in delivered}) == len(delivered)
        assert not {m.id for _, m in delivered} & {m.id for m in bot.unclaimed}
        assert bot.listener.listeners == {}
        bot.assert_every_slot_is_free()


async def test_stress_stop_under_load_then_a_clean_second_run() -> None:
    bot = _Bot(3, WorkersPolicy.REJECT)
    await bot.dispatcher.start()

    for chat in (1, 2, 3):
        bot.wait_on(chat, timeout=30)

    await _until(lambda: (3, ListenerWorkersBusy) in bot.outcomes)

    await asyncio.wait_for(bot.dispatcher.stop(), 3)

    assert sorted(bot.outcomes, key=str) == [
        (1, ListenerCancelled),
        (2, ListenerCancelled),
        (3, ListenerWorkersBusy),
    ]
    assert bot.dispatcher.listener_waits == {}
    assert bot.listener.listeners == {}

    bot.outcomes.clear()
    bot.client.add_handler(RawUpdateHandler(bot.handle))

    async with _running(bot):
        assert bot.dispatcher.listener_waits == {}

        bot.wait_on(1)
        await _until(lambda: MessageKey(1) in bot.listener.listeners)
        answer = make_message(1)
        bot.reply(answer)
        await bot.settle()

        assert bot.outcomes == [(1, answer)]
        bot.assert_every_slot_is_free()


async def test_stress_listeners_of_two_types_share_the_slots_and_keep_their_updates() -> None:
    bot = _Bot(3, WorkersPolicy.CANCEL_OLDEST)
    queries = CallbackQueryListener()
    bot.client.register_listener(queries)

    async with _running(bot):
        query_outcome: list[object] = []

        async def wait_for_query() -> None:
            try:
                query_outcome.append(
                    await queries.listen(CallbackQueryKey(chat_id=1, user_id=7), timeout=5)
                )
            except ListenerError as e:
                query_outcome.append(type(e))

        bot.run(wait_for_query)
        await _until(lambda: CallbackQueryKey(1, 7) in queries.listeners)
        bot.wait_on(1, 7)
        await _until(lambda: MessageKey(1, 7) in bot.listener.listeners)

        # A query with no wait of its type left stays out of the message wait on the same key.
        bot.wait_on(2)
        await _until(lambda: query_outcome == [ListenerEvicted])
        bot.reply(make_callback_query(1, 7), CallbackQueryHandler)
        await asyncio.sleep(0.02)

        assert MessageKey(1, 7) in bot.listener.listeners

        answers = {1: make_message(1, 7), 2: make_message(2)}
        for answer in answers.values():
            bot.reply(answer)

        await bot.settle()

        assert dict(bot.outcomes) == answers
        bot.assert_every_slot_is_free()


async def test_stress_two_clients_share_no_slots() -> None:
    full = _Bot(2, WorkersPolicy.REJECT)
    free = _Bot(2, WorkersPolicy.REJECT)

    async with _running(full), _running(free):
        full.wait_on(1)
        await _until(lambda: MessageKey(1) in full.listener.listeners)
        free.wait_on(1)
        await _until(lambda: MessageKey(1) in free.listener.listeners)

        answer = make_message(1)
        free.reply(answer)
        await free.settle()

        assert free.outcomes == [(1, answer)]
        assert full.outcomes == []
        assert MessageKey(1) in full.listener.listeners

        full.listener.cancel(MessageKey(1))
        await full.settle()


async def test_stress_two_replies_at_once_give_a_wait_exactly_one(
    caplog: pytest.LogCaptureFixture,
) -> None:
    gate = asyncio.Event()

    async def slow_filter(_: object, __: object, update: Message) -> bool:
        await gate.wait()
        return True

    bot = _Bot(4, WorkersPolicy.REJECT)

    async with _running(bot):
        got: list[object] = []

        async def wait_with_a_filter() -> None:
            got.append(
                await bot.listener.listen(
                    MessageKey(chat_id=1), timeout=5, filters=filters.create(slow_filter)
                )
            )

        bot.run(wait_with_a_filter)
        await _until(lambda: MessageKey(1) in bot.listener.listeners)

        replies = [make_message(1, message_id=i) for i in (1, 2, 3)]
        for reply in replies:
            bot.reply(reply)

        await asyncio.sleep(0.01)
        gate.set()
        await bot.settle()

        assert len(got) == 1
        assert sorted(m.id for m in [*got, *bot.unclaimed]) == [1, 2, 3]
        assert "Unexpected error" not in caplog.text  # `handle_listen` would hide a failure
        bot.assert_every_slot_is_free()


def test_key_hold_context_var_starts_empty() -> None:
    assert _HANDLER_HOLD.get() is None
    assert _HANDLER_HOLD.name == "pyroflow_handler_hold"


async def test_a_plain_worker_clears_an_inherited_handler_hold() -> None:
    client = pyroflow.Client(
        "probe", api_id=1, api_hash="x", in_memory=True, workers=1, skip_updates=True
    )
    seen: list[object] = []

    async def record(*_: object) -> None:
        seen.append(_HANDLER_HOLD.get())

    client.add_handler(RawUpdateHandler(record))
    await asyncio.sleep(0)
    token = _HANDLER_HOLD.set(object())  # ty: ignore[invalid-argument-type]
    try:
        await client.dispatcher.start()
    finally:
        _HANDLER_HOLD.reset(token)

    client.dispatcher.updates_queue.put_nowait((object(), {}, {}))  # ty: ignore[invalid-argument-type]
    await asyncio.sleep(0.01)
    await asyncio.wait_for(client.dispatcher.stop(), 5)

    assert seen == [None]
