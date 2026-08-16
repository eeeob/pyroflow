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

import asyncio
import contextvars
from types import SimpleNamespace

import pytest

from pyrogram.types import Message
from pyrogram.utils import get_peer_id

from pyroflow.dispatcher import Dispatcher, _CoordinatedRelease, mark_handled
from pyroflow.errors import UnhandledUpdate
from pyroflow.update_coordinated import MessageCoordinated
from pyroflow.update_coordinator.memory_update_coordinator import (
    MemoryUpdateCoordinator,
)

from .conftest import make_message


CHAT_SCOPE = staticmethod(lambda u: (get_peer_id(u.raw.peer_id),))

PACKET = (None, None, None)


def make_coordinated(**kw):
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


def fake_dispatcher(**kw):
    """A minimal stand-in exposing only what handle_update() touches.

    `client.loop` is among those: the early-settlement path schedules onto it.
    """
    return SimpleNamespace(
        client=SimpleNamespace(loop=asyncio.get_event_loop()), **kw
    )


def make_dispatcher(coordinated, handle_result):
    fake = fake_dispatcher(coordinateds={Message: coordinated})

    async def _handle_update(packet, parsed_update, handler_type):
        if isinstance(handle_result, Exception):
            raise handle_result
        return handle_result

    fake._handle_update = _handle_update
    return fake


def coordinatable_message(message_id=5, chat_id=100, user_id=7):
    """A Message carrying the raw.peer_id that MessageCoordinated keys on."""
    msg = make_message(chat_id, user_id, message_id)
    msg.raw = SimpleNamespace(peer_id=SimpleNamespace(channel_id=chat_id))
    return msg


async def _is_claimed(coordinated, msg):
    """Whether the update is registered as handled, so peers will skip it."""
    return await coordinated.coordinator.is_handled(
        await coordinated.extract_update_id(msg)
    )


async def _is_lock_free(coordinated, msg):
    """Whether this update's lock scope is available to the next caller."""
    return await (await coordinated.lock(msg)).acquire()


# --- what gets registered as handled --------------------------------------


async def test_handled_update_is_claimed_so_peers_skip_it():
    coordinated = make_coordinated()
    msg = coordinatable_message()

    await Dispatcher.handle_update(
        make_dispatcher(coordinated, (1, 0)), PACKET, msg, type(None)
    )

    assert await _is_claimed(coordinated, msg) is True


async def test_raising_handler_still_claims_the_update():
    """A handler that raised still *ran*: the update reached its owner, so
    replaying it on a peer would duplicate work rather than recover.
    `sum(result)` counts exc_count deliberately — see Dispatcher docs."""
    coordinated = make_coordinated()
    msg = coordinatable_message()

    await Dispatcher.handle_update(
        make_dispatcher(coordinated, (0, 2)), PACKET, msg, type(None)
    )

    assert await _is_claimed(coordinated, msg) is True


async def test_untouched_update_is_left_for_a_peer_to_retry():
    coordinated = make_coordinated()
    msg = coordinatable_message()

    await Dispatcher.handle_update(
        make_dispatcher(coordinated, (0, 0)), PACKET, msg, type(None)
    )

    assert await _is_claimed(coordinated, msg) is False


async def test_unhandled_update_hands_the_update_back():
    """Raising UnhandledUpdate stops this session and leaves the update
    unregistered, so a peer may still take it."""
    coordinated = make_coordinated()
    msg = coordinatable_message()
    dispatcher = make_dispatcher(coordinated, UnhandledUpdate("not mine"))

    with pytest.raises(UnhandledUpdate):
        await Dispatcher.handle_update(dispatcher, PACKET, msg, type(None))

    assert await _is_claimed(coordinated, msg) is False


async def test_already_handled_update_is_not_reprocessed():
    coordinated = make_coordinated()
    msg = coordinatable_message()

    # A peer already finished this update.
    await coordinated.coordinator.mark_handled(
        await coordinated.extract_update_id(msg)
    )

    ran = False

    async def _handle_update(*a, **kw):
        nonlocal ran
        ran = True
        return (1, 0)

    fake = fake_dispatcher(coordinateds={Message: coordinated})
    fake._handle_update = _handle_update

    await Dispatcher.handle_update(fake, PACKET, msg, type(None))

    assert ran is False, "update already handled by a peer must not be reprocessed"


async def test_uncoordinated_update_type_passes_straight_through():
    fake = fake_dispatcher(coordinateds={})
    seen = []

    async def _handle_update(packet, parsed_update, handler_type):
        seen.append(parsed_update)
        return (1, 0)

    fake._handle_update = _handle_update
    msg = coordinatable_message()

    await Dispatcher.handle_update(fake, PACKET, msg, type(None))
    assert seen == [msg]


async def test_uncoordinatable_update_is_processed_without_a_lock():
    coordinated = make_coordinated()
    coordinated.is_coordinatable_func = lambda u: False
    msg = coordinatable_message()

    await Dispatcher.handle_update(
        make_dispatcher(coordinated, (1, 0)), PACKET, msg, type(None)
    )

    assert await _is_claimed(coordinated, msg) is False
    assert await _is_lock_free(coordinated, msg) is True


# --- the lock is always given back ----------------------------------------


async def test_lock_is_released_after_a_handled_update():
    """The core regression: the scope must reopen once the update is done.
    The old coordinator kept its key marked forever, so the next update in
    that scope was skipped as an already-handled duplicate."""
    coordinated = make_coordinated()
    msg = coordinatable_message()

    await Dispatcher.handle_update(
        make_dispatcher(coordinated, (1, 0)), PACKET, msg, type(None)
    )

    assert await _is_lock_free(coordinated, msg) is True


async def test_lock_is_released_after_a_raising_handler():
    coordinated = make_coordinated()
    msg = coordinatable_message()
    dispatcher = make_dispatcher(coordinated, RuntimeError("boom"))

    with pytest.raises(RuntimeError):
        await Dispatcher.handle_update(dispatcher, PACKET, msg, type(None))

    assert await _is_lock_free(coordinated, msg) is True


async def test_lock_is_released_when_the_update_was_already_handled():
    """The skip path returns early — from inside the lock. It still has to
    unwind through the settlement, or the scope stays wedged."""
    coordinated = make_coordinated()
    msg = coordinatable_message()
    await coordinated.coordinator.mark_handled(
        await coordinated.extract_update_id(msg)
    )

    await Dispatcher.handle_update(
        make_dispatcher(coordinated, (1, 0)), PACKET, msg, type(None)
    )

    assert await _is_lock_free(coordinated, msg) is True


async def test_lock_is_released_when_identity_extraction_fails():
    """extract_update_id runs *after* the lock is taken, so a hook that
    raises must not strand it."""
    coordinated = make_coordinated()
    coordinated.extract_update_id_func = None      # -> NotImplementedError
    msg = coordinatable_message()

    with pytest.raises(NotImplementedError):
        await Dispatcher.handle_update(
            make_dispatcher(coordinated, (1, 0)), PACKET, msg, type(None)
        )

    assert await _is_lock_free(coordinated, msg) is True


async def test_a_contended_lock_makes_the_update_skip():
    coordinated = make_coordinated(blocking_timeout=0.01)
    msg = coordinatable_message()

    held = await coordinated.lock(msg)
    assert await held.acquire() is True

    ran = False

    async def _handle_update(*a, **kw):
        nonlocal ran
        ran = True
        return (1, 0)

    fake = fake_dispatcher(coordinateds={Message: coordinated})
    fake._handle_update = _handle_update

    await Dispatcher.handle_update(fake, PACKET, msg, type(None))

    assert ran is False, "an update whose scope is locked must be skipped"
    assert await _is_claimed(coordinated, msg) is False, (
        "a skipped update must stay available"
    )


async def test_many_updates_in_a_row_each_get_the_lock():
    coordinated = make_coordinated()

    for i in range(20):
        msg = coordinatable_message(message_id=i)
        await Dispatcher.handle_update(
            make_dispatcher(coordinated, (1, 0)), PACKET, msg, type(None)
        )
        assert await _is_claimed(coordinated, msg) is True


# --- wide lock + narrow identity: ordering without loss -------------------


async def test_chat_wide_lock_serialises_every_update_without_loss():
    """The whole point of splitting the two keys.

    Ten updates arrive concurrently for one chat. The chat-scoped lock must
    make them run strictly one at a time, and the per-message identity must
    keep every one of them from being mistaken for a duplicate."""
    coordinated = make_coordinated(extract_key_func=CHAT_SCOPE, blocking_timeout=5)

    processed = []
    concurrent = peak = 0

    async def _handle_update(packet, parsed_update, handler_type):
        nonlocal concurrent, peak
        concurrent += 1
        peak = max(peak, concurrent)

        await asyncio.sleep(0.01)

        processed.append(parsed_update.id)
        concurrent -= 1
        return (1, 0)

    fake = fake_dispatcher(coordinateds={Message: coordinated})
    fake._handle_update = _handle_update

    await asyncio.gather(*(
        Dispatcher.handle_update(
            fake, PACKET, coordinatable_message(message_id=i), type(None)
        )
        for i in range(10)
    ))

    assert peak == 1, f"chat-wide lock failed to serialise (peak {peak})"
    assert sorted(processed) == list(range(10)), (
        f"updates were lost under a shared lock scope: {sorted(processed)}"
    )


async def test_chat_wide_lock_still_skips_a_redelivered_update():
    coordinated = make_coordinated(extract_key_func=CHAT_SCOPE, blocking_timeout=5)
    runs = []

    async def _handle_update(packet, parsed_update, handler_type):
        runs.append(parsed_update.id)
        return (1, 0)

    fake = fake_dispatcher(coordinateds={Message: coordinated})
    fake._handle_update = _handle_update

    for message_id in (1, 1, 2):
        await Dispatcher.handle_update(
            fake, PACKET, coordinatable_message(message_id=message_id), type(None)
        )

    assert runs == [1, 2], "a redelivered update was processed twice"


async def test_separate_chats_do_not_block_each_other():
    coordinated = make_coordinated(extract_key_func=CHAT_SCOPE, blocking_timeout=5)

    concurrent = peak = 0

    async def _handle_update(packet, parsed_update, handler_type):
        nonlocal concurrent, peak
        concurrent += 1
        peak = max(peak, concurrent)
        await asyncio.sleep(0.01)
        concurrent -= 1
        return (1, 0)

    fake = fake_dispatcher(coordinateds={Message: coordinated})
    fake._handle_update = _handle_update

    await asyncio.gather(*(
        Dispatcher.handle_update(
            fake, PACKET, coordinatable_message(message_id=1, chat_id=c), type(None)
        )
        for c in range(5)
    ))

    assert peak > 1, "distinct chats must not serialise against each other"


# --- early settlement via mark_handled() ----------------------------------


def make_marking_dispatcher(coordinated, body):
    """A dispatcher whose _handle_update runs `body(peer)`.

    `peer` probes coordination from *inside* the handler, while it is still
    running — which is the whole window this feature is about.
    """
    fake = fake_dispatcher(coordinateds={Message: coordinated})

    async def _handle_update(packet, parsed_update, handler_type):
        async def peer():
            return (
                await _is_claimed(coordinated, parsed_update),
                await _is_lock_free(coordinated, parsed_update),
            )

        return await body(peer)

    fake._handle_update = _handle_update
    return fake


async def test_lock_is_held_for_the_whole_handler_by_default():
    """The baseline the feature departs from: without mark_handled() a slow
    handler keeps the scope locked for its entire duration."""
    coordinated = make_coordinated(blocking_timeout=0.01)
    msg = coordinatable_message()

    async def body(peer):
        await asyncio.sleep(0)
        claimed, lock_free = await peer()
        assert claimed is False, "not settled yet"
        assert lock_free is False, "lock must still be held mid-handler"
        return (1, 0)

    await Dispatcher.handle_update(
        make_marking_dispatcher(coordinated, body), PACKET, msg, type(None)
    )


async def test_mark_handled_settles_before_the_handler_returns():
    """The point of the feature: hold time tracks how long the update takes
    to *claim*, not how long the handler takes to *finish*."""
    coordinated = make_coordinated(blocking_timeout=0.05)
    msg = coordinatable_message()

    async def body(peer):
        assert mark_handled() is True
        # Give the scheduled settlement a chance to run, as any awaiting
        # handler inevitably would.
        await asyncio.sleep(0)

        claimed, lock_free = await peer()
        assert claimed is True, "mark_handled() must register the update"
        assert lock_free is True, "mark_handled() must release the lock"

        await asyncio.sleep(0.05)       # the "slow job"
        return (0, 0)

    await Dispatcher.handle_update(
        make_marking_dispatcher(coordinated, body), PACKET, msg, type(None)
    )

    # (0, 0) would normally leave the update unregistered. The early mark
    # must win over that.
    assert await _is_claimed(coordinated, msg) is True


async def test_mark_handled_lets_the_next_update_in_the_scope_start():
    """With a chat-wide lock, settling early is what hands the chat over."""
    coordinated = make_coordinated(extract_key_func=CHAT_SCOPE, blocking_timeout=5)
    order = []

    async def _handle_update(packet, parsed_update, handler_type):
        order.append(("start", parsed_update.id))

        if parsed_update.id == 1:
            mark_handled()
            await asyncio.sleep(0)
            await asyncio.sleep(0.05)      # long tail, lock already gone

        order.append(("end", parsed_update.id))
        return (1, 0)

    fake = fake_dispatcher(coordinateds={Message: coordinated})
    fake._handle_update = _handle_update

    await asyncio.gather(
        Dispatcher.handle_update(
            fake, PACKET, coordinatable_message(message_id=1), type(None)
        ),
        Dispatcher.handle_update(
            fake, PACKET, coordinatable_message(message_id=2), type(None)
        ),
    )

    assert order.index(("start", 2)) < order.index(("end", 1)), (
        "the second update should have started while the first was still running"
    )


async def test_mark_handled_is_idempotent():
    coordinated = make_coordinated()
    msg = coordinatable_message()

    async def body(peer):
        assert mark_handled() is True
        assert mark_handled() is False, "second call must not settle twice"
        return (1, 0)

    await Dispatcher.handle_update(
        make_marking_dispatcher(coordinated, body), PACKET, msg, type(None)
    )

    assert await _is_claimed(coordinated, msg) is True
    assert await _is_lock_free(coordinated, msg) is True


async def test_mark_handled_survives_a_raising_handler():
    """Already settled — an exception afterwards must not hand the update
    back to a peer that would redo the part already done."""
    coordinated = make_coordinated()
    msg = coordinatable_message()

    async def body(peer):
        mark_handled()
        await asyncio.sleep(0)
        raise RuntimeError("boom")

    with pytest.raises(RuntimeError):
        await Dispatcher.handle_update(
            make_marking_dispatcher(coordinated, body), PACKET, msg, type(None)
        )

    assert await _is_claimed(coordinated, msg) is True
    assert await _is_lock_free(coordinated, msg) is True


async def test_mark_handled_works_from_a_sync_handler_in_the_executor():
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

    def sync_handler():
        result["marked"] = mark_handled()

    async def body(peer):
        await asyncio.to_thread(sync_handler)     # copies the context
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


def count_settlements(coordinated):
    """Record every mark_handled() the dispatcher performs."""
    calls = []
    original = coordinated.coordinator.mark_handled

    async def counting(key):
        calls.append(key)
        return await original(key)

    coordinated.coordinator.mark_handled = counting
    return calls


async def test_a_leaked_context_cannot_settle_twice():
    """A handler that spawns background work leaks its context — and with it
    a live reference to the releaser — well past its own return. A late
    mark_handled() from there must not settle a second time: by then the lock
    may have been re-taken by a *later* update, and the stray release would
    hand that update's scope away while it is still being processed."""
    coordinated = make_coordinated()
    calls = count_settlements(coordinated)
    msg = coordinatable_message()
    escaped = {}

    async def body(peer):
        escaped["ctx"] = contextvars.copy_context()    # as create_task() does
        return (1, 0)

    await Dispatcher.handle_update(
        make_marking_dispatcher(coordinated, body), PACKET, msg, type(None)
    )
    assert len(calls) == 1

    # The background task finally gets round to marking.
    assert escaped["ctx"].run(mark_handled) is False
    await asyncio.sleep(0.05)

    assert len(calls) == 1, "the update was settled twice"


async def test_settle_twice_settles_once():
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


async def test_settling_before_the_identity_is_known_marks_nothing():
    """The window between taking the lock and extracting the identity: there
    is nothing to register yet, but the lock must still come back."""
    coordinated = make_coordinated()
    calls = count_settlements(coordinated)
    msg = coordinatable_message()

    lock = await coordinated.lock(msg)
    await lock.acquire()

    release = _CoordinatedRelease(coordinated, lock, asyncio.get_event_loop())
    await release.settle(True)                 # update_id still None

    assert calls == []
    assert await _is_lock_free(coordinated, msg) is True


async def test_mark_handled_outside_update_processing_is_a_noop():
    assert mark_handled() is False


async def test_marker_does_not_leak_between_updates():
    """The ContextVar is reset per update; a handler for update B must not be
    able to settle update A."""
    coordinated = make_coordinated()
    first = coordinatable_message(message_id=1)

    async def body(peer):
        mark_handled()
        return (1, 0)

    await Dispatcher.handle_update(
        make_marking_dispatcher(coordinated, body), PACKET, first, type(None)
    )

    assert mark_handled() is False, "marker outlived the update it belonged to"
