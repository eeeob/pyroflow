"""Dispatcher coordination pipeline: lock lifecycle and handled registration.

These cover `Dispatcher.handle_update`, which drives coordination end to end:
extract the update's key (its lock) and take the lock, check its identity
against the handled registry, then process it. The first listener that
resolves it or handler filter that passes it marks it as handled and releases
the lock early; an update nothing took is released unmarked for a peer.

The fake `_handle_update` below stands in for that first match by awaiting
`_settle_handled()` itself, as the real one does.
"""

from __future__ import annotations as _annotations

import asyncio
import logging
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any, NoReturn

import pytest

from pyrogram import ContinuePropagation, StopPropagation
from pyrogram.handlers import (
    CallbackQueryHandler,
    ErrorHandler,
    MessageHandler,
    RawUpdateHandler,
)
from pyrogram.types import Message

from pyroflow import dispatcher as dispatcher_module
from pyroflow.dispatcher import (
    _SETTLEMENT,
    Dispatcher,
    _CoordinatedRelease,
    _settle_handled,
)
from pyroflow.errors import UnresolvedUpdate, UpdateAlreadyHandled
from pyroflow.update_coordinated import MessageCoordinated
from pyroflow.update_listener import MessageListener
from pyroflow.update_coordinator import RedisUpdateCoordinator
from pyroflow.update_coordinator.memory_update_coordinator import (
    MemoryUpdateCoordinator,
)

from .conftest import make_callback_query, make_message

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable


PACKET = (None, None, None)


def make_coordinated(**kw: Any) -> MessageCoordinated:
    """A MessageCoordinated over an in-memory coordinator, locked per chat by default.

    ``extract_key_func`` may be passed to change the lock key.
    """
    extract_key_func = kw.pop("extract_key_func", None)
    kw.setdefault("blocking_timeout", 0.2)

    return MessageCoordinated(
        extract_key_func=extract_key_func,
        coordinator_factory=lambda ut: MemoryUpdateCoordinator(ut, **kw),
    )


def fake_dispatcher(
    coordinated: object | None,
    body: Callable[[Message], Awaitable[None]] | None = None,
    *,
    settles: bool = True,
    error: BaseException | None = None,
) -> SimpleNamespace:
    """A stand-in exposing only what handle_update() touches.

    Its `_handle_update` runs `body`, settles the update as handled when
    `settles` (as a passing filter does), then raises `error` if given.
    """
    fake = SimpleNamespace(coordinateds={} if coordinated is None else {Message: coordinated})
    fake.ran = []

    async def _handle_update(
        packet: object, parsed_update: Message, handler_type: object
    ) -> tuple[int, int]:
        fake.ran.append(parsed_update.id)

        if body is not None:
            await body(parsed_update)

        if settles:
            await _settle_handled()

        if error is not None:
            raise error

        return (int(settles), 0)

    fake._handle_update = _handle_update
    return fake


def coordinatable_message(message_id: int = 5, chat_id: int = 100, user_id: int = 7) -> Message:
    """A Message carrying the chat that MessageCoordinated keys on."""
    return make_message(chat_id, user_id, message_id)


async def _is_claimed(coordinated: MessageCoordinated, msg: Message) -> bool:
    """Whether the update is registered as handled, so peers will skip it."""
    return await coordinated.coordinator.is_handled(await coordinated.extract_update_id(msg))


async def _is_lock_free(coordinated: MessageCoordinated, msg: Message) -> bool:
    """Whether this update's lock is available to the next caller; releases it again."""
    lock = coordinated.coordinator.lock(await coordinated.extract_key(msg))

    if not await lock.acquire():
        return False

    await lock.release()
    return True


async def handle(fake: SimpleNamespace, msg: Message) -> None:
    await Dispatcher.handle_update(fake, PACKET, msg, type(None))


# --- what gets marked as handled -------------------------------------------


async def test_settled_update_is_marked_and_released() -> None:
    coordinated = make_coordinated()
    msg = coordinatable_message()

    await handle(fake_dispatcher(coordinated), msg)

    assert await _is_claimed(coordinated, msg) is True
    assert await _is_lock_free(coordinated, msg) is True


async def test_unsettled_update_is_released_unmarked_for_a_peer() -> None:
    """No listener and no passing filter: a peer with other handlers may take it."""
    coordinated = make_coordinated()
    msg = coordinatable_message()

    await handle(fake_dispatcher(coordinated, settles=False), msg)

    assert await _is_claimed(coordinated, msg) is False
    assert await _is_lock_free(coordinated, msg) is True


async def test_peer_takes_an_update_this_session_left_unmarked() -> None:
    """Two sessions on one backend, each with its own handlers."""
    coordinated = make_coordinated()
    msg = coordinatable_message()
    first = fake_dispatcher(coordinated, settles=False)
    second = fake_dispatcher(coordinated)

    await handle(first, msg)
    await handle(second, msg)
    await handle(first, msg)

    assert first.ran == [5]
    assert second.ran == [5]
    assert await _is_claimed(coordinated, msg) is True


async def test_handler_error_after_settling_keeps_the_mark() -> None:
    coordinated = make_coordinated()
    msg = coordinatable_message()

    with pytest.raises(RuntimeError):
        await handle(fake_dispatcher(coordinated, error=RuntimeError("boom")), msg)

    assert await _is_claimed(coordinated, msg) is True
    assert await _is_lock_free(coordinated, msg) is True


async def test_error_before_settling_releases_unmarked() -> None:
    coordinated = make_coordinated()
    msg = coordinatable_message()

    with pytest.raises(RuntimeError):
        await handle(fake_dispatcher(coordinated, settles=False, error=RuntimeError("boom")), msg)

    assert await _is_claimed(coordinated, msg) is False
    assert await _is_lock_free(coordinated, msg) is True


async def test_stop_propagation_propagates_with_the_update_still_marked() -> None:
    coordinated = make_coordinated()
    msg = coordinatable_message()

    with pytest.raises(StopPropagation):
        await handle(fake_dispatcher(coordinated, error=StopPropagation()), msg)

    assert await _is_claimed(coordinated, msg) is True
    assert await _is_lock_free(coordinated, msg) is True


async def test_already_handled_update_is_dropped_and_released() -> None:
    coordinated = make_coordinated()
    msg = coordinatable_message()
    await coordinated.coordinator.mark_handled(await coordinated.extract_update_id(msg))
    fake = fake_dispatcher(coordinated)

    await handle(fake, msg)

    assert fake.ran == [], "update already handled by a peer must not be reprocessed"
    assert await _is_lock_free(coordinated, msg) is True


async def test_uncoordinated_update_type_passes_straight_through() -> None:
    settlements: list[object] = []

    async def body(update: Message) -> None:
        settlements.append(_SETTLEMENT.get())

    fake = fake_dispatcher(None, body)

    await handle(fake, coordinatable_message())

    assert fake.ran == [5]
    assert settlements == [None]


async def test_none_key_processes_the_update_without_a_lock() -> None:
    coordinated = make_coordinated(extract_key_func=lambda u: None)
    coordinated.extract_update_id_func = None  # never reached without a key
    settlements: list[object] = []

    async def body(update: Message) -> None:
        settlements.append(_SETTLEMENT.get())

    fake = fake_dispatcher(coordinated, body)

    await handle(fake, coordinatable_message())

    assert fake.ran == [5]
    assert settlements == [None]


async def test_a_contended_lock_makes_the_update_skip(caplog: pytest.LogCaptureFixture) -> None:
    coordinated = make_coordinated(blocking_timeout=0.01)
    msg = coordinatable_message()

    held = coordinated.coordinator.lock(await coordinated.extract_key(msg))
    assert await held.acquire() is True

    fake = fake_dispatcher(coordinated)

    with caplog.at_level(logging.ERROR, logger="pyroflow.dispatcher"):
        await handle(fake, msg)

    assert fake.ran == [], "an update whose lock is held must be skipped"
    assert await _is_claimed(coordinated, msg) is False, "a skipped update must stay available"
    assert "Timeout waiting for coordinated lock" in caplog.text


@pytest.mark.parametrize("stage", ["extract_key", "acquire", "extract_update_id", "is_handled"])
async def test_failing_coordination_setup_processes_uncoordinated(
    stage: str, caplog: pytest.LogCaptureFixture
) -> None:
    coordinated = make_coordinated()
    msg = coordinatable_message()

    def fail(*args: object) -> NoReturn:
        raise RuntimeError(stage)

    if stage == "extract_key":
        coordinated.extract_key_func = fail
    elif stage == "extract_update_id":
        coordinated.extract_update_id_func = fail
    elif stage == "is_handled":
        coordinated.coordinator.is_handled = fail  # ty: ignore[invalid-assignment]
    else:
        coordinated.coordinator.lock = lambda key: SimpleNamespace(acquire=fail)  # ty: ignore[invalid-assignment]

    settlements: list[object] = []

    async def body(update: Message) -> None:
        settlements.append(_SETTLEMENT.get())

    fake = fake_dispatcher(coordinated, body)

    with caplog.at_level(logging.ERROR, logger="pyroflow.dispatcher"):
        await handle(fake, msg)

    assert fake.ran == [5]
    assert settlements == [None]
    assert "Error while setting up coordination" in caplog.text

    if stage in ("extract_update_id", "is_handled"):
        assert await _is_lock_free(coordinated, msg) is True, (
            "a failure after acquire leaked the lock"
        )


# --- early release once handled --------------------------------------------


async def test_settling_releases_the_lock_before_the_handler_returns() -> None:
    coordinated = make_coordinated(blocking_timeout=0.01)
    msg = coordinatable_message()
    seen: dict[str, bool] = {}

    async def body(update: Message) -> None:
        seen["held_before"] = not await _is_lock_free(coordinated, update)
        await _settle_handled()
        seen["claimed"] = await _is_claimed(coordinated, update)
        seen["free_after"] = await _is_lock_free(coordinated, update)

    await handle(fake_dispatcher(coordinated, body, settles=False), msg)

    assert seen == {"held_before": True, "claimed": True, "free_after": True}


async def test_next_update_in_the_chat_starts_while_a_settled_handler_runs() -> None:
    coordinated = make_coordinated(blocking_timeout=1)
    first_running = asyncio.Event()
    second_done = asyncio.Event()

    async def body(update: Message) -> None:
        await _settle_handled()

        if update.id == 1:
            first_running.set()
            await asyncio.wait_for(second_done.wait(), 1)
        else:
            second_done.set()

    fake = fake_dispatcher(coordinated, body, settles=False)

    async def second() -> None:
        await first_running.wait()
        await handle(fake, coordinatable_message(message_id=2))

    await asyncio.gather(handle(fake, coordinatable_message(message_id=1)), second())

    assert fake.ran == [1, 2]


async def test_chat_lock_serialises_updates_until_settled_without_loss() -> None:
    """The chat-level default key: ten concurrent updates of one chat take
    turns until each is settled, and the per-message identity keeps every
    one from being mistaken for a duplicate."""
    coordinated = make_coordinated(blocking_timeout=5)
    concurrent = peak = 0

    async def body(update: Message) -> None:
        nonlocal concurrent, peak
        concurrent += 1
        peak = max(peak, concurrent)
        await asyncio.sleep(0.01)
        concurrent -= 1

    fake = fake_dispatcher(coordinated, body)

    await asyncio.gather(*(handle(fake, coordinatable_message(message_id=i)) for i in range(10)))

    assert peak == 1, f"chat lock failed to serialise (peak {peak})"
    assert sorted(fake.ran) == list(range(10)), f"updates were lost: {sorted(fake.ran)}"


async def test_chat_lock_still_skips_a_redelivered_update() -> None:
    coordinated = make_coordinated(blocking_timeout=5)
    fake = fake_dispatcher(coordinated)

    for message_id in (1, 1, 2):
        await handle(fake, coordinatable_message(message_id=message_id))

    assert fake.ran == [1, 2], "a redelivered update was processed twice"


async def test_separate_chats_do_not_block_each_other() -> None:
    coordinated = make_coordinated(blocking_timeout=5)
    concurrent = peak = 0

    async def body(update: Message) -> None:
        nonlocal concurrent, peak
        concurrent += 1
        peak = max(peak, concurrent)
        await asyncio.sleep(0.01)
        concurrent -= 1

    fake = fake_dispatcher(coordinated, body)

    await asyncio.gather(
        *(handle(fake, coordinatable_message(message_id=1, chat_id=c)) for c in range(5))
    )

    assert peak > 1, "distinct chats must not serialise against each other"


async def test_settlement_is_set_only_while_the_update_is_processed() -> None:
    coordinated = make_coordinated()
    settlements: list[object] = []

    async def body(update: Message) -> None:
        settlements.append(_SETTLEMENT.get())

    await handle(fake_dispatcher(coordinated, body), coordinatable_message())

    assert isinstance(settlements[0], _CoordinatedRelease)
    assert _SETTLEMENT.get() is None


async def test_redis_backend_marks_and_hands_over_across_sessions() -> None:
    fakeredis = pytest.importorskip("fakeredis")
    pytest.importorskip("lupa")
    redis = fakeredis.aioredis.FakeRedis()
    coordinated = MessageCoordinated(
        coordinator_factory=lambda ut: RedisUpdateCoordinator(redis, ut, blocking_timeout=1)
    )
    msg = coordinatable_message()
    first = fake_dispatcher(coordinated, settles=False)
    second = fake_dispatcher(coordinated)

    await handle(first, msg)
    assert await _is_claimed(coordinated, msg) is False

    await handle(second, msg)
    await handle(first, msg)

    assert first.ran == [5]
    assert second.ran == [5]
    assert await _is_claimed(coordinated, msg) is True
    assert await _is_lock_free(coordinated, msg) is True


# --- module-level definitions ----------------------------------------------


def test_module_logger_is_named_after_the_module() -> None:
    assert dispatcher_module.log.name == "pyroflow.dispatcher"


def test_public_surface() -> None:
    assert dispatcher_module.__all__ == ("Dispatcher",)


def test_settlement_context_variable_defaults_to_none() -> None:
    assert _SETTLEMENT.name == "pyroflow_settlement"
    assert _SETTLEMENT.get() is None


# --- _CoordinatedRelease and _settle_handled --------------------------------


class FakeLock:
    def __init__(self, error: Exception | None = None) -> None:
        self.releases = 0
        self.error = error

    async def release(self) -> None:
        self.releases += 1
        if self.error is not None:
            raise self.error


class FakeCoordinator:
    def __init__(self, error: Exception | None = None) -> None:
        self.marked: list[object] = []
        self.error = error

    async def mark_handled(self, update_id: object) -> None:
        self.marked.append(update_id)
        if self.error is not None:
            raise self.error


def make_release(
    coordinator: FakeCoordinator | None = None, lock: FakeLock | None = None
) -> tuple[_CoordinatedRelease, FakeCoordinator, FakeLock]:
    coordinator = coordinator or FakeCoordinator()
    lock = lock or FakeLock()
    release = _CoordinatedRelease(coordinator, lock, ("id",))  # ty: ignore[invalid-argument-type]
    return release, coordinator, lock


async def test_release_starts_unsettled() -> None:
    release, coordinator, lock = make_release()

    assert release._settled is False
    assert coordinator.marked == []
    assert lock.releases == 0


@pytest.mark.parametrize(("handled", "marked"), [(True, [("id",)]), (False, [])])
async def test_settle_marks_only_when_handled_and_always_releases(
    handled: bool, marked: list[object]
) -> None:
    release, coordinator, lock = make_release()

    await release.settle(handled)

    assert coordinator.marked == marked
    assert lock.releases == 1
    assert release._settled is True


async def test_settle_is_a_one_shot() -> None:
    release, coordinator, lock = make_release()

    await release.settle(False)
    await release.settle(True)

    assert coordinator.marked == []
    assert lock.releases == 1


async def test_settle_swallows_a_failing_registration_and_still_releases(
    caplog: pytest.LogCaptureFixture,
) -> None:
    release, coordinator, lock = make_release(coordinator=FakeCoordinator(RuntimeError("down")))

    with caplog.at_level(logging.ERROR, logger="pyroflow.dispatcher"):
        assert await release.settle(True) is True

    assert coordinator.marked == [("id",)]
    assert lock.releases == 1
    assert "Error marking update ('id',) as handled" in caplog.text


async def test_settle_reports_an_update_a_peer_marked_first(
    caplog: pytest.LogCaptureFixture,
) -> None:
    release, _, lock = make_release(coordinator=FakeCoordinator(UpdateAlreadyHandled(("id",))))

    with caplog.at_level(logging.WARNING, logger="pyroflow.dispatcher"):
        assert await release.settle(True) is False

    assert lock.releases == 1
    assert release._settled is True
    assert "already handled by a peer" in caplog.text


async def test_settle_returns_true_once_settled() -> None:
    release, _, _ = make_release()

    assert await release.settle(True) is True
    assert await release.settle(True) is True


async def test_settle_swallows_a_failing_release() -> None:
    release, _, lock = make_release(lock=FakeLock(RuntimeError("down")))

    await release.settle(False)

    assert lock.releases == 1
    assert release._settled is True


async def test_settle_handled_outside_a_coordinated_update_is_a_noop() -> None:
    assert await _settle_handled() is True

    assert _SETTLEMENT.get() is None


async def test_settle_handled_returns_false_for_an_update_a_peer_marked_first() -> None:
    release, _, _ = make_release(coordinator=FakeCoordinator(UpdateAlreadyHandled(("id",))))
    token = _SETTLEMENT.set(release)

    try:
        assert await _settle_handled() is False
    finally:
        _SETTLEMENT.reset(token)


async def test_settle_handled_settles_the_current_update_as_handled() -> None:
    release, coordinator, lock = make_release()
    token = _SETTLEMENT.set(release)

    try:
        await _settle_handled()
    finally:
        _SETTLEMENT.reset(token)

    assert coordinator.marked == [("id",)]
    assert lock.releases == 1


# --- Dispatcher: construction, start and stop -------------------------------


class FakeComponent:
    """A listener or coordinated stand-in bound to `Message`."""

    __update_type__ = Message

    def __init__(self, log: list[str], name: str, error: Exception | None = None) -> None:
        self.log = log
        self.name = name
        self.error = error

    async def start(self) -> None:
        self.log.append(f"start {self.name}")
        if self.error is not None:
            raise self.error

    async def stop(self) -> None:
        self.log.append(f"stop {self.name}")
        if self.error is not None:
            raise self.error


def make_client(**kw: Any) -> SimpleNamespace:
    kw.setdefault("loop", asyncio.get_running_loop())
    return SimpleNamespace(
        executor=None,
        start_handler=None,
        stop_handler=None,
        no_updates=True,
        workers=0,
        skip_updates=True,
        **kw,
    )


def make_real_dispatcher(**kw: Any) -> Dispatcher:
    return Dispatcher(make_client(**kw))


async def test_init_runs_the_original_and_sets_empty_registries() -> None:
    client = make_client()
    dispatcher = Dispatcher(client)

    assert dispatcher.client is client
    assert isinstance(dispatcher.updates_queue, asyncio.Queue)
    assert dispatcher.listeners == {}
    assert dispatcher.coordinateds == {}
    assert dispatcher.is_started is False


async def test_start_and_stop_through_the_original_dispatcher() -> None:
    dispatcher = make_real_dispatcher()

    await dispatcher.start()
    assert dispatcher.is_started is True

    await dispatcher.stop()
    assert dispatcher.is_started is False


async def test_start_runs_the_original_first_then_every_component() -> None:
    order: list[str] = []
    dispatcher = make_real_dispatcher()

    async def oldstart(*args: object, **kw: object) -> object:
        order.append(f"oldstart {args} {kw}")
        assert dispatcher.is_started is False
        return "result"

    dispatcher.oldstart = oldstart
    dispatcher.listeners[Message] = FakeComponent(order, "listener")  # ty: ignore[invalid-assignment]
    dispatcher.coordinateds[Message] = FakeComponent(order, "coordinated")  # ty: ignore[invalid-assignment]

    assert await dispatcher.start(1, flag=True) == "result"

    assert dispatcher.is_started is True
    assert order[0] == "oldstart (1,) {'flag': True}"
    assert sorted(order[1:]) == ["start coordinated", "start listener"]


async def test_start_survives_a_failing_component() -> None:
    order: list[str] = []
    dispatcher = make_real_dispatcher()
    dispatcher.listeners[Message] = FakeComponent(order, "listener", RuntimeError("x"))  # ty: ignore[invalid-assignment]
    dispatcher.coordinateds[Message] = FakeComponent(order, "coordinated")  # ty: ignore[invalid-assignment]

    await dispatcher.start()

    assert dispatcher.is_started is True
    assert sorted(order) == ["start coordinated", "start listener"]


async def test_start_leaves_the_dispatcher_stopped_if_the_original_fails() -> None:
    dispatcher = make_real_dispatcher()

    async def oldstart() -> None:
        msg = "boom"
        raise RuntimeError(msg)

    dispatcher.oldstart = oldstart

    with pytest.raises(RuntimeError):
        await dispatcher.start()

    assert dispatcher.is_started is False


async def test_stop_stops_every_component_before_the_original() -> None:
    order: list[str] = []
    dispatcher = make_real_dispatcher()
    dispatcher.is_started = True

    async def oldstop(*args: object, **kw: object) -> object:
        order.append(f"oldstop {args} {kw}")
        assert dispatcher.is_started is True
        return "result"

    dispatcher.oldstop = oldstop
    dispatcher.listeners[Message] = FakeComponent(order, "listener", RuntimeError("x"))  # ty: ignore[invalid-assignment]
    dispatcher.coordinateds[Message] = FakeComponent(order, "coordinated")  # ty: ignore[invalid-assignment]

    assert await dispatcher.stop(clear_handlers=False) == "result"

    assert dispatcher.is_started is False
    assert sorted(order[:2]) == ["stop coordinated", "stop listener"]
    assert order[2] == "oldstop () {'clear_handlers': False}"


# --- Dispatcher: registration -----------------------------------------------

REGISTRIES = pytest.mark.parametrize(
    ("kind", "registry", "label"),
    [
        ("listener", "listeners", "UpdateListener"),
        ("coordinated", "coordinateds", "UpdateCoordinated"),
    ],
)


@REGISTRIES
async def test_register_stores_by_update_type(kind: str, registry: str, label: str) -> None:
    dispatcher = make_real_dispatcher()
    component = FakeComponent([], kind)

    getattr(dispatcher, f"register_{kind}")(component)

    assert getattr(dispatcher, registry) == {Message: component}


@REGISTRIES
async def test_register_rejects_a_second_for_the_same_type(
    kind: str, registry: str, label: str
) -> None:
    dispatcher = make_real_dispatcher()
    first = FakeComponent([], "first")
    register = getattr(dispatcher, f"register_{kind}")
    register(first)

    with pytest.raises(ValueError, match=f"{label} for .* is already registered"):
        register(FakeComponent([], "second"))

    assert getattr(dispatcher, registry) == {Message: first}


@REGISTRIES
async def test_register_rejects_a_running_dispatcher(kind: str, registry: str, label: str) -> None:
    dispatcher = make_real_dispatcher()
    dispatcher.is_started = True

    with pytest.raises(RuntimeError, match=f"Cannot register {kind} while dispatcher"):
        getattr(dispatcher, f"register_{kind}")(FakeComponent([], kind))

    assert getattr(dispatcher, registry) == {}


@REGISTRIES
async def test_unregister_removes_and_stops(kind: str, registry: str, label: str) -> None:
    order: list[str] = []
    dispatcher = make_real_dispatcher()
    getattr(dispatcher, registry)[Message] = FakeComponent(order, kind)

    await getattr(dispatcher, f"unregister_{kind}")(Message)

    assert getattr(dispatcher, registry) == {}
    assert order == [f"stop {kind}"]


@REGISTRIES
async def test_unregister_unknown_type_is_a_noop(kind: str, registry: str, label: str) -> None:
    order: list[str] = []
    dispatcher = make_real_dispatcher()
    component = FakeComponent(order, kind)
    getattr(dispatcher, registry)[Message] = component

    await getattr(dispatcher, f"unregister_{kind}")(int)

    assert getattr(dispatcher, registry) == {Message: component}
    assert order == []


# --- Dispatcher.handle_listen -----------------------------------------------


class FakeListener:
    __update_type__ = Message

    def __init__(self, error: Exception | None = None) -> None:
        self.resolved: list[object] = []
        self.error = error

    async def resolve(self, update: object) -> None:
        self.resolved.append(update)
        if self.error is not None:
            raise self.error


async def test_handle_listen_resolved_update_stops_propagation() -> None:
    dispatcher = make_real_dispatcher()
    listener = FakeListener()
    dispatcher.listeners[Message] = listener  # ty: ignore[invalid-assignment]
    msg = make_message()

    with pytest.raises(StopPropagation):
        await dispatcher.handle_listen(msg)

    assert listener.resolved == [msg]


async def test_handle_listen_unresolved_update_propagates_on(
    caplog: pytest.LogCaptureFixture,
) -> None:
    dispatcher = make_real_dispatcher()
    listener = FakeListener(UnresolvedUpdate("x"))
    dispatcher.listeners[Message] = listener  # ty: ignore[invalid-assignment]
    msg = make_message()

    with caplog.at_level(logging.ERROR, logger="pyroflow.dispatcher"):
        await dispatcher.handle_listen(msg)

    assert listener.resolved == [msg]
    assert "Unexpected error in handle_listen" not in caplog.text


async def test_handle_listen_lets_an_update_through_an_idle_listener() -> None:
    dispatcher = make_real_dispatcher()
    dispatcher.register_listener(MessageListener())
    release, _, _ = make_release()
    token = _SETTLEMENT.set(release)

    try:
        assert await dispatcher.handle_listen(make_message()) is None
    finally:
        _SETTLEMENT.reset(token)

    assert release._settled is False


async def test_handle_listen_logs_a_listener_error(caplog: pytest.LogCaptureFixture) -> None:
    dispatcher = make_real_dispatcher()
    dispatcher.listeners[Message] = FakeListener(RuntimeError("boom"))  # ty: ignore[invalid-assignment]

    with caplog.at_level(logging.ERROR, logger="pyroflow.dispatcher"):
        await dispatcher.handle_listen(make_message())

    assert "Unexpected error in handle_listen" in caplog.text


async def test_handle_listen_dispatches_on_the_exact_type() -> None:
    dispatcher = make_real_dispatcher()
    listener = FakeListener()
    dispatcher.listeners[Message] = listener  # ty: ignore[invalid-assignment]

    await dispatcher.handle_listen(make_callback_query())

    assert listener.resolved == []


async def test_handle_listen_settles_a_resolved_update_before_stopping() -> None:
    dispatcher = make_real_dispatcher()
    dispatcher.listeners[Message] = FakeListener()  # ty: ignore[invalid-assignment]
    release, coordinator, lock = make_release()
    token = _SETTLEMENT.set(release)

    try:
        with pytest.raises(StopPropagation):
            await dispatcher.handle_listen(make_message())
    finally:
        _SETTLEMENT.reset(token)

    assert coordinator.marked == [("id",)]
    assert lock.releases == 1


async def test_handle_listen_still_stops_an_update_a_peer_marked_first() -> None:
    dispatcher = make_real_dispatcher()
    dispatcher.listeners[Message] = FakeListener()  # ty: ignore[invalid-assignment]
    release, _, lock = make_release(coordinator=FakeCoordinator(UpdateAlreadyHandled(("id",))))
    token = _SETTLEMENT.set(release)

    try:
        with pytest.raises(StopPropagation):
            await dispatcher.handle_listen(make_message())
    finally:
        _SETTLEMENT.reset(token)

    assert lock.releases == 1


async def test_handle_listen_leaves_an_unresolved_update_unsettled() -> None:
    dispatcher = make_real_dispatcher()
    dispatcher.listeners[Message] = FakeListener(UnresolvedUpdate("x"))  # ty: ignore[invalid-assignment]
    release, coordinator, lock = make_release()
    token = _SETTLEMENT.set(release)

    try:
        await dispatcher.handle_listen(make_message())
    finally:
        _SETTLEMENT.reset(token)

    assert release._settled is False


# --- Dispatcher._handle_update ----------------------------------------------

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

    result = await dispatcher._handle_update(RAW_PACKET, msg, MessageHandler)

    assert result == (2, 0)
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

    assert await dispatcher._handle_update(RAW_PACKET, msg, MessageHandler) == (1, 0)
    assert calls == [("message", msg)]


async def test_handler_whose_filter_rejects_is_skipped() -> None:
    dispatcher = make_real_dispatcher()
    calls: list[tuple[object, ...]] = []
    rejecting = MessageHandler(recording(calls, "rejecting"))

    async def reject(client: object, update: object) -> bool:
        return False

    rejecting.check = reject
    dispatcher.groups[0] = [rejecting]

    assert await dispatcher._handle_update(RAW_PACKET, make_message(), MessageHandler) == (0, 0)
    assert calls == []


async def test_raw_handler_receives_the_raw_packet() -> None:
    dispatcher = make_real_dispatcher()
    calls: list[tuple[object, ...]] = []
    dispatcher.groups[0] = [RawUpdateHandler(recording(calls, "raw"))]

    assert await dispatcher._handle_update(RAW_PACKET, None, type(None)) == (1, 0)
    assert calls == [("raw", *RAW_PACKET)]


async def test_no_parsed_update_skips_the_listener() -> None:
    dispatcher = make_real_dispatcher()
    listener = FakeListener()
    dispatcher.listeners[type(None)] = listener  # ty: ignore[invalid-assignment]

    assert await dispatcher._handle_update(RAW_PACKET, None, type(None)) == (0, 0)
    assert listener.resolved == []


async def test_resolved_listener_stops_before_any_handler() -> None:
    dispatcher = make_real_dispatcher()
    calls: list[tuple[object, ...]] = []
    dispatcher.listeners[Message] = FakeListener()  # ty: ignore[invalid-assignment]
    dispatcher.groups[0] = [MessageHandler(recording(calls, "a"))]

    with pytest.raises(StopPropagation):
        await dispatcher._handle_update(RAW_PACKET, make_message(), MessageHandler)

    assert calls == []


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
        result = await dispatcher._handle_update(RAW_PACKET, msg, MessageHandler)

    assert result == (1, 0)
    assert calls == [("next", msg)]
    assert message in caplog.text


async def test_continue_propagation_tries_the_next_handler_uncounted() -> None:
    dispatcher = make_real_dispatcher()
    calls: list[tuple[object, ...]] = []
    msg = make_message()
    dispatcher.groups[0] = [
        MessageHandler(recording(calls, "a", ContinuePropagation())),
        MessageHandler(recording(calls, "b")),
    ]

    assert await dispatcher._handle_update(RAW_PACKET, msg, MessageHandler) == (1, 0)
    assert calls == [("a", msg), ("b", msg)]


async def test_stop_propagation_propagates_out() -> None:
    error = StopPropagation()
    dispatcher = make_real_dispatcher()
    calls: list[tuple[object, ...]] = []
    msg = make_message()
    dispatcher.groups[0] = [MessageHandler(recording(calls, "a", error))]
    dispatcher.groups[1] = [MessageHandler(recording(calls, "b"))]

    with pytest.raises(type(error)):
        await dispatcher._handle_update(RAW_PACKET, msg, MessageHandler)

    assert calls == [("a", msg)]


async def test_handler_error_is_counted_and_reported_then_the_group_ends() -> None:
    dispatcher = make_real_dispatcher()
    seen = capture_handler_exceptions(dispatcher)
    calls: list[tuple[object, ...]] = []
    msg = make_message()
    error = RuntimeError("boom")
    broken = MessageHandler(recording(calls, "broken", error))
    dispatcher.groups[0] = [broken, MessageHandler(recording(calls, "same-group"))]
    dispatcher.groups[1] = [MessageHandler(recording(calls, "other-group"))]

    assert await dispatcher._handle_update(RAW_PACKET, msg, MessageHandler) == (1, 1)
    assert calls == [("broken", msg), ("other-group", msg)]
    assert seen == [(error, broken, *RAW_PACKET)]


async def test_passing_filter_settles_the_update_before_its_handler_runs() -> None:
    dispatcher = make_real_dispatcher()
    release, coordinator, lock = make_release()
    settled_in_handler: list[bool] = []

    async def callback(client: object, update: object) -> None:
        settled_in_handler.append(release._settled)

    dispatcher.groups[0] = [MessageHandler(callback)]
    dispatcher.groups[1] = [MessageHandler(callback)]
    token = _SETTLEMENT.set(release)

    try:
        await dispatcher._handle_update(RAW_PACKET, make_message(), MessageHandler)
    finally:
        _SETTLEMENT.reset(token)

    assert settled_in_handler == [True, True]
    assert coordinator.marked == [("id",)]
    assert lock.releases == 1


async def test_update_a_peer_marked_first_runs_no_handler() -> None:
    dispatcher = make_real_dispatcher()
    calls: list[tuple[object, ...]] = []
    release, _, lock = make_release(coordinator=FakeCoordinator(UpdateAlreadyHandled(("id",))))
    dispatcher.groups[0] = [MessageHandler(recording(calls, "a"))]
    dispatcher.groups[1] = [MessageHandler(recording(calls, "b"))]
    token = _SETTLEMENT.set(release)

    try:
        assert await dispatcher._handle_update(RAW_PACKET, make_message(), MessageHandler) == (
            0,
            0,
        )
    finally:
        _SETTLEMENT.reset(token)

    assert calls == []
    assert lock.releases == 1


async def test_rejecting_filters_leave_the_update_unsettled() -> None:
    dispatcher = make_real_dispatcher()
    calls: list[tuple[object, ...]] = []
    rejecting = MessageHandler(recording(calls, "rejecting"))

    async def reject(client: object, update: object) -> bool:
        return False

    rejecting.check = reject
    dispatcher.groups[0] = [rejecting]
    release, _, _ = make_release()
    token = _SETTLEMENT.set(release)

    try:
        await dispatcher._handle_update(RAW_PACKET, make_message(), MessageHandler)
    finally:
        _SETTLEMENT.reset(token)

    assert release._settled is False


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
