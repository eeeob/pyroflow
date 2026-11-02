"""Dispatcher coordination pipeline: lock lifecycle and handled registration.

These cover `Dispatcher.handle_update`, which drives coordination end to end:
take the update's lock scope, check its identity against the handled
registry, process it, register it, release.

The headline guarantee is the pairing of a *wide* lock with a *narrow*
identity — serialising a whole chat while every update in it still gets
processed exactly once. Keying both from one value is the bug this design
replaced: the first update would register the entire chat as handled and
every update after it would be silently dropped.
"""

from __future__ import annotations as _annotations

import asyncio
import contextvars
import logging
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any, NoReturn

import pytest

from pyrogram import ContinuePropagation, StopPropagation, raw
from pyrogram.handlers import (
    CallbackQueryHandler,
    ErrorHandler,
    MessageHandler,
    RawUpdateHandler,
)
from pyrogram.types import Message
from pyrogram.utils import get_peer_id

from pyroflow import dispatcher as dispatcher_module
from pyroflow.dispatcher import (
    _HANDLED_MARKER,
    Dispatcher,
    _CoordinatedRelease,
    mark_handled,
)
from pyroflow.errors import UnhandledUpdate, UnresolvedUpdate
from pyroflow.update_coordinated import MessageCoordinated
from pyroflow.update_coordinator.memory_update_coordinator import (
    MemoryUpdateCoordinator,
)

from .conftest import make_callback_query, make_message

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from pyroflow.typings import UpdateCoordinatorKeyT

    # يعيد (claimed, lock_free) من داخل الـ handler.
    PeerProbe = Callable[[], Awaitable[tuple[bool, bool]]]


CHAT_SCOPE = staticmethod(lambda u: (get_peer_id(u.raw.peer_id),))

PACKET = (None, None, None)


def make_coordinated(**kw: Any) -> MessageCoordinated:
    """A MessageCoordinated over an in-memory coordinator.

    ``extract_key_func`` may be passed to widen the lock scope; the default
    keeps it at one update, matching the shipped behaviour.
    """
    extract_key_func = kw.pop("extract_key_func", None)
    kw.setdefault("blocking_timeout", 0.2)

    return MessageCoordinated(
        extract_key_func=extract_key_func,
        coordinator_factory=lambda ut: MemoryUpdateCoordinator(ut, **kw),
    )


def fake_dispatcher(**kw: Any) -> SimpleNamespace:
    """A minimal stand-in exposing only what handle_update() touches.

    `client.loop` is among those: the early-settlement path schedules onto it.
    """
    return SimpleNamespace(client=SimpleNamespace(loop=asyncio.get_event_loop()), **kw)


def make_dispatcher(
    coordinated: MessageCoordinated, handle_result: tuple[int, int] | Exception
) -> SimpleNamespace:
    fake = fake_dispatcher(coordinateds={Message: coordinated})

    async def _handle_update(
        packet: object, parsed_update: Message, handler_type: object
    ) -> tuple[int, int]:
        if isinstance(handle_result, Exception):
            raise handle_result
        return handle_result

    fake._handle_update = _handle_update
    return fake


def coordinatable_message(message_id: int = 5, chat_id: int = 100, user_id: int = 7) -> Message:
    """A Message carrying the raw.peer_id that MessageCoordinated keys on."""
    msg = make_message(chat_id, user_id, message_id)
    msg.raw = SimpleNamespace(peer_id=raw.types.PeerChannel(channel_id=chat_id))
    return msg


async def _is_claimed(coordinated: MessageCoordinated, msg: Message) -> bool:
    """Whether the update is registered as handled, so peers will skip it."""
    return await coordinated.coordinator.is_handled(await coordinated.extract_update_id(msg))


async def _is_lock_free(coordinated: MessageCoordinated, msg: Message) -> bool:
    """Whether this update's lock scope is available to the next caller."""
    return await (await coordinated.lock(msg)).acquire()


# --- what gets registered as handled --------------------------------------


async def test_handled_update_is_claimed_so_peers_skip_it() -> None:
    coordinated = make_coordinated()
    msg = coordinatable_message()

    await Dispatcher.handle_update(make_dispatcher(coordinated, (1, 0)), PACKET, msg, type(None))

    assert await _is_claimed(coordinated, msg) is True


async def test_raising_handler_still_claims_the_update() -> None:
    """A handler that raised still *ran*: the update reached its owner, so
    replaying it on a peer would duplicate work rather than recover.
    `sum(result)` counts exc_count deliberately — see Dispatcher docs."""
    coordinated = make_coordinated()
    msg = coordinatable_message()

    await Dispatcher.handle_update(make_dispatcher(coordinated, (0, 2)), PACKET, msg, type(None))

    assert await _is_claimed(coordinated, msg) is True


async def test_untouched_update_is_left_for_a_peer_to_retry() -> None:
    coordinated = make_coordinated()
    msg = coordinatable_message()

    await Dispatcher.handle_update(make_dispatcher(coordinated, (0, 0)), PACKET, msg, type(None))

    assert await _is_claimed(coordinated, msg) is False


async def test_unhandled_update_hands_the_update_back() -> None:
    """Raising UnhandledUpdate stops this session and leaves the update
    unregistered, so a peer may still take it."""
    coordinated = make_coordinated()
    msg = coordinatable_message()
    dispatcher = make_dispatcher(coordinated, UnhandledUpdate("not mine"))

    with pytest.raises(UnhandledUpdate):
        await Dispatcher.handle_update(dispatcher, PACKET, msg, type(None))

    assert await _is_claimed(coordinated, msg) is False


async def test_already_handled_update_is_not_reprocessed() -> None:
    coordinated = make_coordinated()
    msg = coordinatable_message()

    # A peer already finished this update.
    await coordinated.coordinator.mark_handled(await coordinated.extract_update_id(msg))

    ran = False

    async def _handle_update(*a: object, **kw: object) -> tuple[int, int]:
        nonlocal ran
        ran = True
        return (1, 0)

    fake = fake_dispatcher(coordinateds={Message: coordinated})
    fake._handle_update = _handle_update

    await Dispatcher.handle_update(fake, PACKET, msg, type(None))

    assert ran is False, "update already handled by a peer must not be reprocessed"


async def test_uncoordinated_update_type_passes_straight_through() -> None:
    fake = fake_dispatcher(coordinateds={})
    seen = []

    async def _handle_update(
        packet: object, parsed_update: Message, handler_type: object
    ) -> tuple[int, int]:
        seen.append(parsed_update)
        return (1, 0)

    fake._handle_update = _handle_update
    msg = coordinatable_message()

    await Dispatcher.handle_update(fake, PACKET, msg, type(None))
    assert seen == [msg]


async def test_uncoordinatable_update_is_processed_without_a_lock() -> None:
    coordinated = make_coordinated()
    coordinated.is_coordinatable_func = lambda u: False
    msg = coordinatable_message()

    await Dispatcher.handle_update(make_dispatcher(coordinated, (1, 0)), PACKET, msg, type(None))

    assert await _is_claimed(coordinated, msg) is False
    assert await _is_lock_free(coordinated, msg) is True


# --- the lock is always given back ----------------------------------------


async def test_lock_is_released_after_a_handled_update() -> None:
    """The core regression: the scope must reopen once the update is done.
    The old coordinator kept its key marked forever, so the next update in
    that scope was skipped as an already-handled duplicate."""
    coordinated = make_coordinated()
    msg = coordinatable_message()

    await Dispatcher.handle_update(make_dispatcher(coordinated, (1, 0)), PACKET, msg, type(None))

    assert await _is_lock_free(coordinated, msg) is True


async def test_lock_is_released_after_a_raising_handler() -> None:
    coordinated = make_coordinated()
    msg = coordinatable_message()
    dispatcher = make_dispatcher(coordinated, RuntimeError("boom"))

    with pytest.raises(RuntimeError):
        await Dispatcher.handle_update(dispatcher, PACKET, msg, type(None))

    assert await _is_lock_free(coordinated, msg) is True


async def test_lock_is_released_when_the_update_was_already_handled() -> None:
    """The skip path returns early — from inside the lock. It still has to
    unwind through the settlement, or the scope stays wedged."""
    coordinated = make_coordinated()
    msg = coordinatable_message()
    await coordinated.coordinator.mark_handled(await coordinated.extract_update_id(msg))

    await Dispatcher.handle_update(make_dispatcher(coordinated, (1, 0)), PACKET, msg, type(None))

    assert await _is_lock_free(coordinated, msg) is True


async def test_lock_is_released_when_identity_extraction_fails() -> None:
    """extract_update_id runs *after* the lock is taken, so a hook that
    raises must not strand it."""
    coordinated = make_coordinated()
    coordinated.extract_update_id_func = None  # -> NotImplementedError
    msg = coordinatable_message()

    with pytest.raises(NotImplementedError):
        await Dispatcher.handle_update(
            make_dispatcher(coordinated, (1, 0)), PACKET, msg, type(None)
        )

    assert await _is_lock_free(coordinated, msg) is True


async def test_a_contended_lock_makes_the_update_skip(caplog: pytest.LogCaptureFixture) -> None:
    coordinated = make_coordinated(blocking_timeout=0.01)
    msg = coordinatable_message()

    held = await coordinated.lock(msg)
    assert await held.acquire() is True

    ran = False

    async def _handle_update(*a: object, **kw: object) -> tuple[int, int]:
        nonlocal ran
        ran = True
        return (1, 0)

    fake = fake_dispatcher(coordinateds={Message: coordinated})
    fake._handle_update = _handle_update

    with caplog.at_level(logging.ERROR, logger="pyroflow.dispatcher"):
        await Dispatcher.handle_update(fake, PACKET, msg, type(None))

    assert ran is False, "an update whose scope is locked must be skipped"
    assert await _is_claimed(coordinated, msg) is False, "a skipped update must stay available"
    assert "Timeout waiting for coordinated lock" in caplog.text


# --- wide lock + narrow identity: ordering without loss -------------------


async def test_chat_wide_lock_serialises_every_update_without_loss() -> None:
    """The whole point of splitting the two keys.

    Ten updates arrive concurrently for one chat. The chat-scoped lock must
    make them run strictly one at a time, and the per-message identity must
    keep every one of them from being mistaken for a duplicate."""
    coordinated = make_coordinated(extract_key_func=CHAT_SCOPE, blocking_timeout=5)

    processed = []
    concurrent = peak = 0

    async def _handle_update(
        packet: object, parsed_update: Message, handler_type: object
    ) -> tuple[int, int]:
        nonlocal concurrent, peak
        concurrent += 1
        peak = max(peak, concurrent)

        await asyncio.sleep(0.01)

        processed.append(parsed_update.id)
        concurrent -= 1
        return (1, 0)

    fake = fake_dispatcher(coordinateds={Message: coordinated})
    fake._handle_update = _handle_update

    await asyncio.gather(
        *(
            Dispatcher.handle_update(fake, PACKET, coordinatable_message(message_id=i), type(None))
            for i in range(10)
        )
    )

    assert peak == 1, f"chat-wide lock failed to serialise (peak {peak})"
    assert sorted(processed) == list(range(10)), (
        f"updates were lost under a shared lock scope: {sorted(processed)}"
    )


async def test_chat_wide_lock_still_skips_a_redelivered_update() -> None:
    coordinated = make_coordinated(extract_key_func=CHAT_SCOPE, blocking_timeout=5)
    runs = []

    async def _handle_update(
        packet: object, parsed_update: Message, handler_type: object
    ) -> tuple[int, int]:
        runs.append(parsed_update.id)
        return (1, 0)

    fake = fake_dispatcher(coordinateds={Message: coordinated})
    fake._handle_update = _handle_update

    for message_id in (1, 1, 2):
        await Dispatcher.handle_update(
            fake, PACKET, coordinatable_message(message_id=message_id), type(None)
        )

    assert runs == [1, 2], "a redelivered update was processed twice"


async def test_separate_chats_do_not_block_each_other() -> None:
    coordinated = make_coordinated(extract_key_func=CHAT_SCOPE, blocking_timeout=5)

    concurrent = peak = 0

    async def _handle_update(
        packet: object, parsed_update: Message, handler_type: object
    ) -> tuple[int, int]:
        nonlocal concurrent, peak
        concurrent += 1
        peak = max(peak, concurrent)
        await asyncio.sleep(0.01)
        concurrent -= 1
        return (1, 0)

    fake = fake_dispatcher(coordinateds={Message: coordinated})
    fake._handle_update = _handle_update

    await asyncio.gather(
        *(
            Dispatcher.handle_update(
                fake, PACKET, coordinatable_message(message_id=1, chat_id=c), type(None)
            )
            for c in range(5)
        )
    )

    assert peak > 1, "distinct chats must not serialise against each other"


# --- early settlement via mark_handled() ----------------------------------


def make_marking_dispatcher(
    coordinated: MessageCoordinated, body: Callable[[PeerProbe], Awaitable[tuple[int, int]]]
) -> SimpleNamespace:
    """A dispatcher whose _handle_update runs `body(peer)`.

    `peer` probes coordination from *inside* the handler, while it is still
    running — which is the whole window this feature is about.
    """
    fake = fake_dispatcher(coordinateds={Message: coordinated})

    async def _handle_update(
        packet: object, parsed_update: Message, handler_type: object
    ) -> tuple[int, int]:
        async def peer() -> tuple[bool, bool]:
            return (
                await _is_claimed(coordinated, parsed_update),
                await _is_lock_free(coordinated, parsed_update),
            )

        return await body(peer)

    fake._handle_update = _handle_update
    return fake


async def test_lock_is_held_for_the_whole_handler_by_default() -> None:
    """The baseline the feature departs from: without mark_handled() a slow
    handler keeps the scope locked for its entire duration."""
    coordinated = make_coordinated(blocking_timeout=0.01)
    msg = coordinatable_message()

    async def body(peer: PeerProbe) -> tuple[int, int]:
        await asyncio.sleep(0)
        claimed, lock_free = await peer()
        assert claimed is False, "not settled yet"
        assert lock_free is False, "lock must still be held mid-handler"
        return (1, 0)

    await Dispatcher.handle_update(
        make_marking_dispatcher(coordinated, body), PACKET, msg, type(None)
    )


async def test_mark_handled_settles_before_the_handler_returns() -> None:
    """The point of the feature: hold time tracks how long the update takes
    to *claim*, not how long the handler takes to *finish*."""
    coordinated = make_coordinated(blocking_timeout=0.05)
    msg = coordinatable_message()

    async def body(peer: PeerProbe) -> tuple[int, int]:
        assert mark_handled() is True
        # Give the scheduled settlement a chance to run, as any awaiting
        # handler inevitably would.
        await asyncio.sleep(0)

        claimed, lock_free = await peer()
        assert claimed is True, "mark_handled() must register the update"
        assert lock_free is True, "mark_handled() must release the lock"

        await asyncio.sleep(0.05)  # the "slow job"
        return (0, 0)

    await Dispatcher.handle_update(
        make_marking_dispatcher(coordinated, body), PACKET, msg, type(None)
    )

    # (0, 0) would normally leave the update unregistered. The early mark
    # must win over that.
    assert await _is_claimed(coordinated, msg) is True


async def test_mark_handled_lets_the_next_update_in_the_scope_start() -> None:
    """With a chat-wide lock, settling early is what hands the chat over."""
    coordinated = make_coordinated(extract_key_func=CHAT_SCOPE, blocking_timeout=5)
    order = []

    async def _handle_update(
        packet: object, parsed_update: Message, handler_type: object
    ) -> tuple[int, int]:
        order.append(("start", parsed_update.id))

        if parsed_update.id == 1:
            mark_handled()
            await asyncio.sleep(0)
            await asyncio.sleep(0.05)  # long tail, lock already gone

        order.append(("end", parsed_update.id))
        return (1, 0)

    fake = fake_dispatcher(coordinateds={Message: coordinated})
    fake._handle_update = _handle_update

    await asyncio.gather(
        Dispatcher.handle_update(fake, PACKET, coordinatable_message(message_id=1), type(None)),
        Dispatcher.handle_update(fake, PACKET, coordinatable_message(message_id=2), type(None)),
    )

    assert order.index(("start", 2)) < order.index(("end", 1)), (
        "the second update should have started while the first was still running"
    )


async def test_mark_handled_is_idempotent() -> None:
    coordinated = make_coordinated()
    msg = coordinatable_message()

    async def body(peer: PeerProbe) -> tuple[int, int]:
        assert mark_handled() is True
        assert mark_handled() is False, "second call must not settle twice"
        return (1, 0)

    await Dispatcher.handle_update(
        make_marking_dispatcher(coordinated, body), PACKET, msg, type(None)
    )

    assert await _is_claimed(coordinated, msg) is True
    assert await _is_lock_free(coordinated, msg) is True


async def test_mark_handled_survives_a_raising_handler() -> None:
    """Already settled — an exception afterwards must not hand the update
    back to a peer that would redo the part already done."""
    coordinated = make_coordinated()
    msg = coordinatable_message()

    async def body(peer: PeerProbe) -> NoReturn:
        mark_handled()
        await asyncio.sleep(0)
        msg = "boom"
        raise RuntimeError(msg)

    with pytest.raises(RuntimeError):
        await Dispatcher.handle_update(
            make_marking_dispatcher(coordinated, body), PACKET, msg, type(None)
        )

    assert await _is_claimed(coordinated, msg) is True
    assert await _is_lock_free(coordinated, msg) is True


async def test_mark_handled_works_from_a_sync_handler_in_the_executor() -> None:
    """Sync handlers run through to_thread, off the event loop. The
    settlement has to be scheduled thread-safely rather than awaited, which
    is why mark_handled() is a plain function.

    Unlike the same-loop early-settlement path (create_task, one hop to its
    first step), claim_early() off-loop goes through
    run_coroutine_threadsafe: one hop for call_soon_threadsafe's callback to
    create the task, then another for the task's own first step. A single
    ``await asyncio.sleep(0)`` yields exactly one hop — enough for the
    same-loop case, not guaranteed enough once a real OS thread and an extra
    scheduling hop are both in the way. A short real sleep, not a bare tick,
    is what actually waits the settlement out."""
    coordinated = make_coordinated()
    msg = coordinatable_message()
    result = {}

    def sync_handler() -> None:
        result["marked"] = mark_handled()

    async def body(peer: PeerProbe) -> tuple[int, int]:
        await asyncio.to_thread(sync_handler)  # copies the context
        await asyncio.sleep(0.05)

        claimed, lock_free = await peer()
        assert claimed is True
        assert lock_free is True
        return (0, 0)

    await Dispatcher.handle_update(
        make_marking_dispatcher(coordinated, body), PACKET, msg, type(None)
    )

    assert result["marked"] is True
    assert await _is_claimed(coordinated, msg) is True


def count_settlements(coordinated: MessageCoordinated) -> list[UpdateCoordinatorKeyT]:
    """Record every mark_handled() the dispatcher performs."""
    calls = []
    original = coordinated.coordinator.mark_handled

    async def counting(key: UpdateCoordinatorKeyT) -> None:
        calls.append(key)
        return await original(key)

    coordinated.coordinator.mark_handled = counting
    return calls


async def test_a_leaked_context_cannot_settle_twice() -> None:
    """A handler that spawns background work leaks its context — and with it
    a live reference to the releaser — well past its own return. A late
    mark_handled() from there must not settle a second time: by then the lock
    may have been re-taken by a *later* update, and the stray release would
    hand that update's scope away while it is still being processed."""
    coordinated = make_coordinated()
    calls = count_settlements(coordinated)
    msg = coordinatable_message()
    escaped = {}

    async def body(peer: PeerProbe) -> tuple[int, int]:
        escaped["ctx"] = contextvars.copy_context()  # as create_task() does
        return (1, 0)

    await Dispatcher.handle_update(
        make_marking_dispatcher(coordinated, body), PACKET, msg, type(None)
    )
    assert len(calls) == 1

    # The background task finally gets round to marking.
    assert escaped["ctx"].run(mark_handled) is False
    await asyncio.sleep(0.05)

    assert len(calls) == 1, "the update was settled twice"


async def test_settle_twice_settles_once() -> None:
    """The releaser is a one-shot regardless of who calls it or how often."""
    coordinated = make_coordinated()
    calls = count_settlements(coordinated)
    msg = coordinatable_message()

    lock = await coordinated.lock(msg)
    await lock.acquire()

    release = _CoordinatedRelease(coordinated, lock, asyncio.get_event_loop())
    release.update_id = await coordinated.extract_update_id(msg)

    await release.settle(True)
    await release.settle(True)

    assert len(calls) == 1
    assert await _is_lock_free(coordinated, msg) is True


async def test_settling_before_the_identity_is_known_marks_nothing() -> None:
    """The window between taking the lock and extracting the identity: there
    is nothing to register yet, but the lock must still come back."""
    coordinated = make_coordinated()
    calls = count_settlements(coordinated)
    msg = coordinatable_message()

    lock = await coordinated.lock(msg)
    await lock.acquire()

    release = _CoordinatedRelease(coordinated, lock, asyncio.get_event_loop())
    await release.settle(True)  # update_id still None

    assert calls == []
    assert await _is_lock_free(coordinated, msg) is True


async def test_mark_handled_outside_update_processing_is_a_noop() -> None:
    assert mark_handled() is False


async def test_marker_does_not_leak_between_updates() -> None:
    """The ContextVar is reset per update: the handler of a later, uncoordinated
    update in the same context must not see the earlier update's releaser."""
    coordinated = make_coordinated()

    async def body(peer: PeerProbe) -> tuple[int, int]:
        return (1, 0)

    await Dispatcher.handle_update(
        make_marking_dispatcher(coordinated, body), PACKET, coordinatable_message(), type(None)
    )

    seen: list[object] = []

    async def _handle_update(*a: object, **kw: object) -> tuple[int, int]:
        seen.append(_HANDLED_MARKER.get())
        return (1, 0)

    uncoordinated = fake_dispatcher(coordinateds={})
    uncoordinated._handle_update = _handle_update

    await Dispatcher.handle_update(uncoordinated, PACKET, coordinatable_message(), type(None))

    assert seen == [None], "marker outlived the update it belonged to"


# --- module-level definitions ----------------------------------------------


def test_module_logger_is_named_after_the_module() -> None:
    assert dispatcher_module.log.name == "pyroflow.dispatcher"


def test_public_surface() -> None:
    assert dispatcher_module.__all__ == ("Dispatcher", "mark_handled")


# --- _CoordinatedRelease ----------------------------------------------------


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
    release = _CoordinatedRelease(
        SimpleNamespace(coordinator=coordinator), lock, asyncio.get_running_loop()
    )
    return release, coordinator, lock


async def test_claim_early_on_the_loop_schedules_a_handled_settlement() -> None:
    release, coordinator, lock = make_release()
    release.update_id = "id"

    assert release.claim_early() is True
    assert isinstance(release._early, asyncio.Task)
    assert release.claim_early() is False, "a second claim must lose"

    # `handled=False` is ignored: the early settlement already won.
    await release.settle(False)

    assert coordinator.marked == ["id"]
    assert lock.releases == 1


async def test_claim_early_after_settlement_is_refused() -> None:
    release, coordinator, lock = make_release()
    release.update_id = "id"

    await release.settle(False)

    assert release.claim_early() is False
    assert release._early is None
    assert coordinator.marked == []
    assert lock.releases == 1


async def test_claim_early_from_another_thread_is_thread_safe() -> None:
    release, coordinator, lock = make_release()
    release.update_id = "id"

    assert await asyncio.to_thread(release.claim_early) is True
    assert not isinstance(release._early, asyncio.Task)

    await release.settle(False)

    assert coordinator.marked == ["id"]
    assert lock.releases == 1


async def test_settle_swallows_a_failing_registration_and_still_releases() -> None:
    release, coordinator, lock = make_release(coordinator=FakeCoordinator(RuntimeError("down")))
    release.update_id = "id"

    await release.settle(True)

    assert coordinator.marked == ["id"]
    assert lock.releases == 1


async def test_settle_swallows_a_failing_release() -> None:
    release, _, lock = make_release(lock=FakeLock(RuntimeError("down")))

    await release.settle(False)

    assert lock.releases == 1
    assert release._released is True


# --- Dispatcher: construction, start and stop -------------------------------


class FakeComponent:
    """A listener, coordinated or history stand-in bound to `Message`."""

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
    assert dispatcher.histories == {}
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
    dispatcher.histories[Message] = FakeComponent(order, "history")  # ty: ignore[invalid-assignment]

    assert await dispatcher.start(1, flag=True) == "result"

    assert dispatcher.is_started is True
    assert order[0] == "oldstart (1,) {'flag': True}"
    assert sorted(order[1:]) == ["start coordinated", "start history", "start listener"]


async def test_start_survives_a_failing_component() -> None:
    order: list[str] = []
    dispatcher = make_real_dispatcher()
    dispatcher.listeners[Message] = FakeComponent(order, "listener", RuntimeError("x"))  # ty: ignore[invalid-assignment]
    dispatcher.histories[Message] = FakeComponent(order, "history")  # ty: ignore[invalid-assignment]

    await dispatcher.start()

    assert dispatcher.is_started is True
    assert sorted(order) == ["start history", "start listener"]


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
    dispatcher.histories[Message] = FakeComponent(order, "history")  # ty: ignore[invalid-assignment]

    assert await dispatcher.stop(clear_handlers=False) == "result"

    assert dispatcher.is_started is False
    assert sorted(order[:3]) == ["stop coordinated", "stop history", "stop listener"]
    assert order[3] == "oldstop () {'clear_handlers': False}"


# --- Dispatcher: registration -----------------------------------------------

REGISTRIES = pytest.mark.parametrize(
    ("kind", "registry", "label"),
    [
        ("listener", "listeners", "UpdateListener"),
        ("coordinated", "coordinateds", "UpdateCoordinated"),
        ("history", "histories", "UpdateHistory"),
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


@pytest.mark.parametrize("error", [StopPropagation(), UnhandledUpdate("x")])
async def test_stop_and_unhandled_propagate_out(error: Exception) -> None:
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


class FakeHistory:
    __update_type__ = Message

    def __init__(
        self,
        recordable: bool = True,
        recordable_error: Exception | None = None,
        record_error: Exception | None = None,
    ) -> None:
        self.recordable = recordable
        self.recordable_error = recordable_error
        self.record_error = record_error
        self.recorded: list[tuple[object, list[object], bool]] = []

    async def is_recordable(self, update: object) -> bool:
        if self.recordable_error is not None:
            raise self.recordable_error
        return self.recordable

    async def record_many(self, update: object, handlers: list[object], check: bool) -> None:
        self.recorded.append((update, list(handlers), check))
        if self.record_error is not None:
            raise self.record_error


def history_dispatcher(
    history: FakeHistory,
) -> tuple[Dispatcher, list[MessageHandler]]:
    dispatcher = make_real_dispatcher()
    capture_handler_exceptions(dispatcher)
    calls: list[tuple[object, ...]] = []
    handlers = [
        MessageHandler(recording(calls, "ok")),
        MessageHandler(recording(calls, "broken", RuntimeError("boom"))),
        MessageHandler(recording(calls, "ok2")),
    ]
    for group, handler in enumerate(handlers):
        dispatcher.groups[group] = [handler]
    dispatcher.histories[Message] = history  # ty: ignore[invalid-assignment]
    return dispatcher, handlers


async def test_recordable_update_records_only_the_handlers_that_succeeded() -> None:
    history = FakeHistory()
    dispatcher, handlers = history_dispatcher(history)
    msg = make_message()

    assert await dispatcher._handle_update(RAW_PACKET, msg, MessageHandler) == (2, 1)
    assert history.recorded == [(msg, [handlers[0], handlers[2]], False)]


async def test_unrecordable_update_records_nothing() -> None:
    history = FakeHistory(recordable=False)
    dispatcher, _ = history_dispatcher(history)

    assert await dispatcher._handle_update(RAW_PACKET, make_message(), MessageHandler) == (2, 1)
    assert history.recorded == []


async def test_failing_is_recordable_is_logged_and_handlers_still_run(
    caplog: pytest.LogCaptureFixture,
) -> None:
    history = FakeHistory(recordable_error=RuntimeError("down"))
    dispatcher, _ = history_dispatcher(history)

    with caplog.at_level(logging.ERROR, logger="pyroflow.dispatcher"):
        result = await dispatcher._handle_update(RAW_PACKET, make_message(), MessageHandler)

    assert result == (2, 1)
    assert history.recorded == []
    assert "Unexpected error checking is_recordable" in caplog.text


async def test_failing_record_many_is_logged_not_raised(caplog: pytest.LogCaptureFixture) -> None:
    history = FakeHistory(record_error=RuntimeError("down"))
    dispatcher, _ = history_dispatcher(history)

    with caplog.at_level(logging.ERROR, logger="pyroflow.dispatcher"):
        result = await dispatcher._handle_update(RAW_PACKET, make_message(), MessageHandler)

    assert result == (2, 1)
    assert len(history.recorded) == 1
    assert "Unexpected error recording handlers" in caplog.text


async def test_nothing_succeeded_records_nothing() -> None:
    history = FakeHistory()
    dispatcher = make_real_dispatcher()
    capture_handler_exceptions(dispatcher)
    dispatcher.groups[0] = [MessageHandler(recording([], "broken", RuntimeError("boom")))]
    dispatcher.histories[Message] = history  # ty: ignore[invalid-assignment]

    assert await dispatcher._handle_update(RAW_PACKET, make_message(), MessageHandler) == (0, 1)
    assert history.recorded == []


# --- Dispatcher.handle_update: remaining branches ---------------------------


async def test_stop_propagation_still_claims_a_coordinated_update() -> None:
    coordinated = make_coordinated()
    msg = coordinatable_message()

    with pytest.raises(StopPropagation):
        await Dispatcher.handle_update(
            make_dispatcher(coordinated, StopPropagation()), PACKET, msg, type(None)
        )

    assert await _is_claimed(coordinated, msg) is True
    assert await _is_lock_free(coordinated, msg) is True


async def test_failing_coordination_setup_processes_uncoordinated(
    caplog: pytest.LogCaptureFixture,
) -> None:
    async def is_coordinatable(update: object) -> bool:
        msg = "down"
        raise RuntimeError(msg)

    coordinated = SimpleNamespace(is_coordinatable=is_coordinatable)
    seen: list[object] = []

    async def _handle_update(
        packet: object, parsed_update: object, handler_type: object
    ) -> tuple[int, int]:
        seen.append(parsed_update)
        assert mark_handled() is False, "no coordination while uncoordinated"
        return (1, 0)

    fake = fake_dispatcher(coordinateds={Message: coordinated})
    fake._handle_update = _handle_update
    msg = coordinatable_message()

    with caplog.at_level(logging.ERROR, logger="pyroflow.dispatcher"):
        await Dispatcher.handle_update(fake, PACKET, msg, type(None))

    assert seen == [msg]
    assert "Error while acquiring coordinated lock" in caplog.text


async def test_marker_is_set_only_while_the_update_is_processed() -> None:
    coordinated = make_coordinated()
    msg = coordinatable_message()
    markers: list[object] = []

    async def body(peer: PeerProbe) -> tuple[int, int]:
        markers.append(_HANDLED_MARKER.get())
        return (1, 0)

    await Dispatcher.handle_update(
        make_marking_dispatcher(coordinated, body), PACKET, msg, type(None)
    )

    assert isinstance(markers[0], _CoordinatedRelease)
    assert markers[0].update_id == await coordinated.extract_update_id(msg)
    assert _HANDLED_MARKER.get() is None


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
    errors = iter([StopPropagation(), UnhandledUpdate("x"), RuntimeError("boom"), None])
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
    for update in ("stop", "unhandled", "boom", "bad-parse", "ok"):
        dispatcher.updates_queue.put_nowait((update, {}, {}))
    dispatcher.updates_queue.put_nowait(None)
    dispatcher.updates_queue.put_nowait(("after-sentinel", {}, {}))

    with caplog.at_level(logging.ERROR, logger="pyroflow.dispatcher"):
        await dispatcher.handler_worker(asyncio.Lock())

    assert handled == ["stop", "unhandled", "boom", "ok"]
    assert caplog.text.count("Unexpected error in handler_worker") == 2
    assert dispatcher.updates_queue.qsize() == 1, "the worker must stop at the sentinel"
