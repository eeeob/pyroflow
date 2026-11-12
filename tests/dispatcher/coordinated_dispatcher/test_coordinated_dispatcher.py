"""CoordinatedDispatcher: one handler at a time per key, with real clients and real workers.

Every wait is bounded, so a regression fails instead of hanging. Nothing here
touches a network: updates go straight into the dispatcher's queue.
"""

from __future__ import annotations as _annotations

import asyncio
import gc
import logging
import random
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, Any

import pytest
from pyrogram import ContinuePropagation, StopPropagation, filters
from pyrogram.handlers import MessageHandler, RawUpdateHandler
from pyrogram.types import Message

import pyroflow
from pyroflow.dispatcher.coordinated_dispatcher import coordinated_dispatcher as coordinated_module
from pyroflow.dispatcher.coordinated_dispatcher.coordinated_dispatcher import (
    ArrivalOrder,
    ZeroWaitCounter,
)
from pyroflow.dispatcher import CoordinatedDispatcher
from pyroflow.dispatcher.dispatcher import _HANDLER_WORKER, _HANDLER_HOLD, Dispatcher
from pyroflow.enums import WorkersPolicy
from pyroflow.errors import (
    ListenerCancelled,
    ListenerEvicted,
    ListenerRejected,
    ListenerReplaced,
    ListenerTimeout,
    ListenerWorkersBusy,
)
from pyroflow.models import MessageKey
from pyroflow.dispatcher.coordinated_dispatcher.models import (
    _HandlerHold,
    _Lane,
    _UpdateToParse,
    _UpdateToRun,
)
from pyroflow.update_listener import MessageListener

from ...conftest import make_message
from . import conftest as sequencing
from .conftest import make_entry

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Callable, Collection


CHAT = 100
USER = 7
KEY = (CHAT, USER)


def by_user(update: Any) -> tuple[int, int]:
    return (update.chat.id, update.from_user.id)


def by_chat(update: Any) -> int:
    return update.chat.id


async def _until(condition: Callable[[], object], timeout: float = 5) -> None:
    # Polled in the calling task: before 3.12, `asyncio.wait_for` runs its coroutine in a task of its own.
    deadline = asyncio.get_running_loop().time() + timeout

    while not condition():
        if asyncio.get_running_loop().time() > deadline:
            raise asyncio.TimeoutError

        await asyncio.sleep(0.002)


def _ids(*ids: int) -> filters.Filter:
    """A filter for the messages `ids`; async, as a sync one needs a client's loop."""

    async def check(_: object, __: object, update: Message) -> bool:
        return update.id in ids

    return filters.create(check)


def _paused(gate: asyncio.Event, inside: list[int], *, passes: bool = True) -> filters.Filter:
    """A filter that answers once `gate` is set, as one doing I/O would."""

    async def check(_: object, __: object, update: Message) -> bool:
        inside.append(update.id)
        await gate.wait()
        return passes

    return filters.create(check)


class _Packet:
    """A raw update stand-in that carries its parsed form."""

    def __init__(self, parsed: object, handler_type: type) -> None:
        self.parsed = parsed
        self.handler_type = handler_type


class _GatedListener(MessageListener):
    """A listener that holds chosen offers open before they resolve."""

    def __init__(self) -> None:
        super().__init__()
        self.before: dict[int, asyncio.Event] = {}
        self.paused: dict[int, asyncio.Task] = {}

    async def resolve(self, update: Message) -> bool:
        gate = self.before.get(update.id)
        if gate is not None:
            self.paused[update.id] = asyncio.current_task()  # ty: ignore[invalid-assignment]
            await gate.wait()
        return await super().resolve(update)


class _Bot:
    """A real client with real workers, driven through its update queue."""

    def __init__(
        self,
        workers: int = 3,
        key: Callable[[Any], object] = by_user,
        listener: MessageListener | None = None,
        policy: WorkersPolicy | None = None,
    ) -> None:
        self.client = pyroflow.Client(
            "probe", api_id=1, api_hash="x", in_memory=True, workers=workers, skip_updates=True
        )
        self.dispatcher = CoordinatedDispatcher(self.client, key_functions=[key])
        self.client.dispatcher = self.dispatcher
        self.client.setup_pyroflow(workers_policy=policy)
        self.listener = listener or MessageListener()
        self.client.register_listener(self.listener)
        self.dispatcher.update_parsers[_Packet] = self.parse
        self.handled: list[int] = []
        self.replies: list[int] = []
        self.pending: list[_Packet] = []
        """Updates sent before the start; `start` would drop them, so `_running` sends them after."""

    @staticmethod
    async def parse(update: _Packet, users: object, chats: object) -> tuple[object, type]:
        return update.parsed, update.handler_type

    def on(self, callback: Any, flt: filters.Filter | None = None, group: int = 0) -> None:
        self.client.add_handler(MessageHandler(callback, flt), group)

    def send_update(self, parsed: object, handler_type: type = MessageHandler) -> None:
        if self.dispatcher.is_started:
            self.dispatcher.enqueue(_Packet(parsed, handler_type), users={}, chats={})  # ty: ignore[invalid-argument-type]
        else:
            self.pending.append(_Packet(parsed, handler_type))

    def send(self, *ids: int, user: int = USER) -> None:
        for message_id in ids:
            self.send_update(make_message(CHAT, user, message_id))

    async def ask(self, user: int | None = USER, **kw: Any) -> int:
        """Wait in `self.listener` with a bound, and record the reply."""
        kw.setdefault("timeout", 5)
        reply = await self.listener.listen(MessageKey(CHAT, user), **kw)
        self.replies.append(reply.id)
        return reply.id

    def queued(self, key: object = KEY) -> list[int]:
        state = self.dispatcher.lanes_by_key.get((0, key))
        return [] if state is None else [item.parsed_update.id for item in state.waiting_updates]

    async def settle(self) -> None:
        """Wait until the queue and the dispatcher hold nothing."""
        dispatcher = self.dispatcher
        await _until(
            lambda: (
                dispatcher.updates_queue.empty()
                and dispatcher.arrival_order.all_admitted.is_set()
                and dispatcher.unfinished_updates is not None
                and dispatcher.unfinished_updates._count == 0
            )
        )


@asynccontextmanager
async def _running(bot: _Bot) -> AsyncIterator[_Bot]:
    await bot.dispatcher.start()
    # Sent before any worker runs, so they wait as a backlog.
    for packet in bot.pending:
        bot.dispatcher.enqueue(packet, users={}, chats={})  # ty: ignore[invalid-argument-type]
    bot.pending.clear()
    try:
        yield bot
    finally:
        await asyncio.wait_for(bot.dispatcher.stop(), 5)


def _bare_client(workers: int = 3) -> pyroflow.Client:
    return pyroflow.Client(
        "probe", api_id=1, api_hash="x", in_memory=True, workers=workers, skip_updates=True
    )


# --- module-level definitions -----------------------------------------------


def test_public_surface() -> None:
    assert (
        coordinated_module.log.name
        == "pyroflow.dispatcher.coordinated_dispatcher.coordinated_dispatcher"
    )
    assert coordinated_module.__all__ == ("CoordinatedDispatcher",)
    assert pyroflow.dispatcher.__all__ == ("Dispatcher", "CoordinatedDispatcher")
    assert pyroflow.CoordinatedDispatcher is CoordinatedDispatcher
    assert issubclass(CoordinatedDispatcher, Dispatcher)


def test_the_base_dispatcher_is_not_patched() -> None:
    assert not hasattr(Dispatcher, "dispatch")
    assert type(_bare_client().dispatcher) is Dispatcher


# --- installing it ----------------------------------------------------------


# --- extract_key ------------------------------------------------------------


# --- the hold and the queue -------------------------------------------------


async def test_a_reply_right_behind_the_first_message_reaches_its_wait() -> None:
    bot = _Bot()

    async def ask(_: object, message: Message) -> None:
        bot.handled.append(message.id)
        await asyncio.sleep(0.01)  # `ask` sends its question first
        await bot.ask()

    bot.on(ask)
    async with _running(bot):
        bot.send(1, 2)
        await _until(lambda: bot.replies)
        await bot.settle()

    assert (bot.handled, bot.replies) == ([1], [2])


async def test_the_key_stays_held_while_the_handler_waits() -> None:
    bot = _Bot()
    log: list[str] = []

    async def ask(_: object, message: Message) -> None:
        log.append(f"start {message.id}")
        if message.id == 1:
            await bot.ask(filters=_ids(3))
            await asyncio.sleep(0.01)
        log.append(f"end {message.id}")

    bot.on(ask)
    async with _running(bot):
        bot.send(1)
        await _until(lambda: bot.listener.listeners)
        bot.send(2, 3)
        await _until(lambda: "end 2" in log)
        await bot.settle()

    assert bot.replies == [3]
    assert log == ["start 1", "end 1", "start 2", "end 2"]


async def test_queued_messages_reach_the_waits_in_order() -> None:
    bot = _Bot()

    async def ask(_: object, message: Message) -> None:
        bot.handled.append(message.id)
        await asyncio.sleep(0.01)
        for _step in range(3):
            await bot.ask()

    bot.on(ask)
    async with _running(bot):
        bot.send(1, 2, 3, 4)
        await _until(lambda: len(bot.replies) == 3)
        await bot.settle()

    assert (bot.handled, bot.replies) == ([1], [2, 3, 4])


async def test_a_message_rejected_by_a_strict_wait_is_not_offered_to_the_next_one() -> None:
    bot = _Bot()
    outcomes: list[object] = []

    async def ask(_: object, message: Message) -> None:
        bot.handled.append(message.id)
        if message.id != 1:
            return
        for _step in range(2):
            try:
                outcomes.append(await bot.ask(filters=_ids(3), strict=True))
            except ListenerRejected:
                outcomes.append("rejected")

    bot.on(ask)
    async with _running(bot):
        bot.send(1)
        await _until(lambda: bot.listener.listeners)
        bot.send(2)
        await _until(lambda: outcomes)
        await _until(lambda: bot.listener.listeners)
        await asyncio.sleep(0.02)  # a second offer of 2 would reject this wait too

        assert outcomes == ["rejected"]

        bot.send(3)
        await _until(lambda: len(bot.handled) == 2)
        await bot.settle()

    assert outcomes == ["rejected", 3]
    assert bot.handled == [1, 2]


async def test_a_queued_message_can_end_a_later_strict_wait() -> None:
    bot = _Bot()
    outcomes: list[object] = []

    async def ask(_: object, message: Message) -> None:
        bot.handled.append(message.id)
        if message.id == 1:
            await _until(lambda: bot.queued() == [2])
            try:
                await bot.ask(filters=_ids(3), strict=True)
            except ListenerRejected:
                outcomes.append("rejected")

    bot.on(ask)
    async with _running(bot):
        bot.send(1, 2)
        await _until(lambda: outcomes and len(bot.handled) == 2)
        await bot.settle()

    assert outcomes == ["rejected"]


async def test_a_message_no_wait_looked_at_reaches_a_later_wait() -> None:
    bot = _Bot(key=by_chat)

    async def ask(_: object, message: Message) -> None:
        bot.handled.append(message.id)
        await bot.ask()
        await bot.ask(user=8)

    bot.on(ask)
    async with _running(bot):
        bot.send(1)
        await _until(lambda: bot.listener.listeners)
        bot.send(2, user=8)
        await _until(lambda: bot.queued(CHAT) == [2])
        bot.send(3)
        await _until(lambda: len(bot.replies) == 2)
        await bot.settle()

    assert (bot.handled, bot.replies) == ([1], [3, 2])


async def test_a_wait_that_starts_with_a_queue_gets_it_from_its_head() -> None:
    bot = _Bot()

    async def ask(_: object, message: Message) -> None:
        bot.handled.append(message.id)
        if message.id == 1:
            await _until(lambda: bot.queued() == [2, 3])
            await bot.ask(filters=_ids(2, 3))
            await bot.ask(filters=_ids(2, 3))

    bot.on(ask)
    async with _running(bot):
        bot.send(1, 2, 3)
        await _until(lambda: len(bot.replies) == 2)
        await bot.settle()

    assert (bot.handled, bot.replies) == ([1], [2, 3])


async def test_rapid_messages_cost_no_workers_while_another_user_is_served() -> None:
    bot = _Bot(workers=3)
    release = asyncio.Event()
    served: list[int] = []

    async def handler(_: object, message: Message) -> None:
        if message.from_user.id != USER:
            served.append(message.id)
            return
        bot.handled.append(message.id)
        await release.wait()

    bot.on(handler)
    async with _running(bot):
        bot.send(*range(1, 13))
        await _until(lambda: len(bot.queued()) == 11)
        bot.send(50, user=8)
        await _until(lambda: served)

        assert bot.handled == [1]

        release.set()
        await _until(lambda: len(bot.handled) == 12)
        await bot.settle()

    assert bot.handled == list(range(1, 13))


async def test_a_queued_update_runs_in_a_worker() -> None:
    bot = _Bot()
    inside: list[bool] = []

    async def probe(_: object, message: Message) -> None:
        inside.append(_HANDLER_WORKER.get() is asyncio.current_task())
        await asyncio.sleep(0.01)

    bot.on(probe)
    async with _running(bot):
        bot.send(1, 2, 3)
        await _until(lambda: len(inside) == 3)
        await bot.settle()

    assert inside == [True] * 3


async def test_add_handler_gets_in_between_two_queued_updates() -> None:
    bot = _Bot()
    late: list[int] = []

    async def record(_: object, message: Message) -> None:
        late.append(message.id)

    async def first(_: object, message: Message) -> None:
        bot.handled.append(message.id)
        if message.id == 1:
            await _until(lambda: bot.queued() == [2, 3])
            bot.on(record, group=1)

    bot.on(first)
    async with _running(bot):
        bot.send(1, 2, 3)
        await _until(lambda: len(late) == 2)
        await bot.settle()

    assert bot.handled == [1, 2, 3]
    assert late == [2, 3]


async def test_a_failing_handler_frees_the_key(caplog: pytest.LogCaptureFixture) -> None:
    bot = _Bot()

    async def fail(_: object, message: Message) -> None:
        bot.handled.append(message.id)
        msg = "boom"
        raise RuntimeError(msg)

    bot.on(fail)
    async with _running(bot):
        bot.send(1, 2)
        await _until(lambda: len(bot.handled) == 2)
        await bot.settle()

    assert "boom" in caplog.text


async def test_stop_propagation_keeps_serving_the_backlog_and_logs_nothing(
    caplog: pytest.LogCaptureFixture,
) -> None:
    bot = _Bot()

    async def stop_here(_: object, message: Message) -> None:
        bot.handled.append(message.id)
        await asyncio.sleep(0.01)
        raise StopPropagation

    bot.on(stop_here)
    async with _running(bot):
        bot.send(1, 2)
        await _until(lambda: len(bot.handled) == 2)
        await bot.settle()

    assert "Unexpected error" not in caplog.text


async def test_a_sync_handler_waits_through_the_hold_of_its_thread() -> None:
    bot = _Bot()

    def ask(_: object, message: Message) -> None:
        bot.handled.append(message.id)
        asyncio.run_coroutine_threadsafe(bot.ask(), loop).result(5)

    loop = asyncio.get_running_loop()
    bot.on(ask)
    async with _running(bot):
        bot.send(1, 2)
        await _until(lambda: bot.replies)
        await bot.settle()

    assert (bot.handled, bot.replies) == ([1], [2])


async def test_gathered_waits_in_spawned_tasks_both_count() -> None:
    bot = _Bot()
    replies: list[Message] = []

    async def ask(_: object, message: Message) -> None:
        bot.handled.append(message.id)
        await asyncio.sleep(0.01)
        by_user_wait = bot.listener.listen(MessageKey(CHAT, USER), filters=_ids(2), timeout=5)
        by_chat_wait = bot.listener.listen(MessageKey(CHAT), filters=_ids(3), timeout=5)
        replies.extend(await asyncio.gather(by_user_wait, by_chat_wait))

    bot.on(ask)
    async with _running(bot):
        bot.send(1, 2, 3)
        await _until(lambda: replies)
        await bot.settle()

    assert bot.handled == [1]
    assert [reply.id for reply in replies] == [2, 3]


async def test_a_handler_of_the_backlog_gets_a_queued_reply() -> None:
    bot = _Bot()

    async def ask(_: object, message: Message) -> None:
        bot.handled.append(message.id)
        if message.id == 1:
            await _until(lambda: bot.queued() == [2, 3])
        elif message.id == 2:
            await bot.ask(timeout=1)

    bot.on(ask)
    async with _running(bot):
        bot.send(1, 2, 3)
        await _until(lambda: bot.replies or len(bot.handled) == 3)
        await bot.settle()

    assert (bot.handled, bot.replies) == ([1, 2], [3])


async def test_strict_filter_ends_a_wait_and_sends_the_update_to_the_handlers() -> None:
    async def not_a_command(_: object, __: object, update: Message) -> bool:
        return update.id != 2

    bot = _Bot(listener=MessageListener(strict_filter=filters.create(not_a_command)))
    outcomes: list[str] = []

    async def ask(_: object, message: Message) -> None:
        bot.handled.append(message.id)
        if message.id == 1:
            try:
                await bot.listener.listen(MessageKey(CHAT, USER))
            except ListenerRejected:
                outcomes.append("rejected")

    bot.on(ask)
    async with _running(bot):
        bot.send(1)
        await _until(lambda: bot.listener.listeners)
        bot.send(2)
        await _until(lambda: 2 in bot.handled)
        await bot.settle()

    assert outcomes == ["rejected"]


async def test_a_wait_that_outlives_its_handler_gets_the_next_queued_update() -> None:
    bot = _Bot()
    waits: list[asyncio.Future] = []

    async def ask(_: object, message: Message) -> None:
        bot.handled.append(message.id)
        if message.id == 1:
            await _until(lambda: bot.queued() == [2])
            waits.append(asyncio.ensure_future(bot.ask()))
            await asyncio.sleep(0)

    bot.on(ask)
    async with _running(bot):
        bot.send(1, 2)
        await _until(lambda: bot.replies)
        await bot.settle()
        await waits[0]

    assert (bot.handled, bot.replies) == ([1], [2])


async def test_a_reply_taken_during_an_offer_is_not_run_when_the_handler_ends_first() -> None:
    gated = _GatedListener()
    gate = asyncio.Event()
    bot = _Bot(listener=gated)

    async def ask(_: object, message: Message) -> None:
        bot.handled.append(message.id)
        if message.id == 1:
            await _until(lambda: bot.queued() == [2, 3])
            gated.before[2] = gate
            waiting = asyncio.ensure_future(bot.ask())
            await _until(lambda: 2 in gated.paused)
            waiting.add_done_callback(lambda _: None)

    bot.on(ask)
    async with _running(bot):
        bot.send(1, 2, 3)
        await _until(lambda: 2 in gated.paused)
        await asyncio.sleep(0.01)  # the handler ended; its worker waits for the offer

        assert bot.handled == [1]

        gate.set()
        await _until(lambda: len(bot.handled) == 2)
        await bot.settle()

    assert (bot.handled, bot.replies) == ([1, 3], [2])


async def test_an_update_without_a_key_stays_uncoordinated() -> None:
    bot = _Bot(key=lambda _: None)
    release = asyncio.Event()
    holds: list[object] = []

    async def handler(_: object, message: Message) -> None:
        bot.handled.append(message.id)
        holds.append(_HANDLER_HOLD.get())
        await release.wait()

    bot.on(handler)
    async with _running(bot):
        bot.send(1, 2)
        await _until(lambda: len(bot.handled) == 2)

        assert bot.dispatcher.lanes_by_key == {}

        release.set()

    assert holds == [None, None]


async def test_an_update_without_a_key_still_reaches_its_wait() -> None:
    bot = _Bot(key=lambda _: None)

    async def ask(_: object, message: Message) -> None:
        bot.handled.append(message.id)
        await bot.ask()

    bot.on(ask)
    async with _running(bot):
        bot.send(1)
        await _until(lambda: bot.listener.listeners)
        bot.send(2)
        await _until(lambda: bot.replies)

    assert (bot.handled, bot.replies) == ([1], [2])


async def test_each_handler_runs_in_a_hold_of_its_own() -> None:
    bot = _Bot()
    seen: list[Any] = []

    async def probe(_: object, message: Message) -> None:
        seen.append(_HANDLER_HOLD.get())
        await asyncio.sleep(0.01)

    bot.on(probe)
    async with _running(bot):
        bot.send(1, 2)
        await _until(lambda: len(seen) == 2)
        await bot.settle()

    assert all(isinstance(hold, _HandlerHold) and hold.handler_ended() for hold in seen)
    assert seen[0] is not seen[1]


async def test_a_client_started_inside_a_handler_takes_no_hold_from_it() -> None:
    outer = _Bot()
    inner = _Bot(key=lambda _: None)

    async def start_inner(_: object, message: Message) -> None:
        outer.handled.append(message.id)
        if message.id == 1:
            await inner.dispatcher.start()
            inner.send(50)
            await _until(lambda: inner.handled)

    async def record(_: object, message: Message) -> None:
        inner.handled.append(message.id)
        assert _HANDLER_HOLD.get() is None

    outer.on(start_inner)
    inner.on(record)
    async with _running(outer):
        outer.send(1, 2)
        await _until(lambda: len(outer.handled) == 2)
        await outer.settle()
        await asyncio.wait_for(inner.dispatcher.stop(), 5)

    assert (outer.handled, inner.handled) == ([1, 2], [50])


async def test_thousands_of_keys_leave_no_state_behind() -> None:
    bot = _Bot()

    async def record(_: object, message: Message) -> None:
        bot.handled.append(message.id)

    bot.on(record)
    async with _running(bot):
        for user in range(5000):
            bot.send(user, user=user)
        await _until(lambda: len(bot.handled) == 5000)
        await bot.settle()


# --- waits from outside the key's handler -----------------------------------


async def test_a_foreign_wait_gets_an_update_that_arrives_while_the_queue_is_offered() -> None:
    # The wait of the handler ends while the offer of 2 waits on its filter.
    gate = asyncio.Event()
    inside: list[int] = []
    bot = _Bot(key=by_chat)
    foreign: list[object] = []

    async def ask(_: object, message: Message) -> None:
        bot.handled.append(message.id)
        if message.id == 1:
            await _until(lambda: bot.queued(CHAT) == [2])
            with pytest.raises(ListenerCancelled):
                await bot.ask(filters=_paused(gate, inside, passes=False))

    async def wait_for_8() -> None:
        foreign.append((await bot.listener.listen(MessageKey(CHAT, 8), timeout=5)).id)

    bot.on(ask)
    async with _running(bot):
        waiting = asyncio.ensure_future(wait_for_8())
        bot.send(1, 2)
        await _until(lambda: inside == [2])
        bot.send(3, user=8)
        await _until(lambda: bot.queued(CHAT) == [2, 3])
        bot.listener.cancel(MessageKey(CHAT, USER))
        gate.set()
        await asyncio.wait_for(waiting, 5)
        await _until(lambda: 2 in bot.handled)
        await bot.settle()

    assert foreign == [3]
    assert bot.handled == [1, 2]


async def test_a_foreign_wait_filters_a_queued_update_once() -> None:
    bot = _Bot(key=by_chat)
    calls: list[int] = []

    async def count(_: object, __: object, update: Message) -> bool:
        calls.append(update.id)
        return False

    async def ask(_: object, message: Message) -> None:
        bot.handled.append(message.id)
        if message.id == 1:
            await _until(lambda: bot.queued(CHAT) == [3])
            with pytest.raises(ListenerCancelled):
                await bot.ask(filters=_ids(99))

    bot.on(ask)
    async with _running(bot):
        waiting = asyncio.ensure_future(
            bot.listener.listen(MessageKey(CHAT, 8), filters=filters.create(count), timeout=5)
        )
        bot.send(1)
        await _until(lambda: 1 in bot.handled)
        bot.send(3, user=8)
        await _until(lambda: calls)
        await _until(lambda: MessageKey(CHAT, USER) in bot.listener.listeners)
        bot.listener.cancel(MessageKey(CHAT, USER))
        await _until(lambda: 3 in bot.handled)
        await bot.settle()
        bot.listener.cancel(MessageKey(CHAT, 8))
        with pytest.raises(ListenerCancelled):
            await waiting

    assert calls == [3]


# --- waits that start during an offer ---------------------------------------


async def test_a_wait_waits_for_the_offer_under_way_then_gets_the_older_updates_first() -> None:
    gated = _GatedListener()
    gate = asyncio.Event()
    go = asyncio.Event()
    bot = _Bot(listener=gated)

    async def ask(_: object, message: Message) -> None:
        bot.handled.append(message.id)
        if message.id == 1:
            await go.wait()
            await bot.ask()

    bot.on(ask)
    async with _running(bot):
        bot.send(1, 2, 3)
        await _until(lambda: bot.queued() == [2, 3])
        await asyncio.sleep(0.01)  # 2 and 3 were offered, and no wait took them
        gated.before[4] = gate
        bot.send(4)
        await _until(lambda: 4 in gated.paused)
        go.set()
        await asyncio.sleep(0.01)
        # The handler's wait starts once 4 is no longer on offer.
        assert MessageKey(CHAT, USER) not in bot.listener.listeners
        gate.set()
        await _until(lambda: bot.replies)
        await _until(lambda: len(bot.handled) == 3)
        await bot.settle()

    assert bot.replies == [2]
    assert bot.handled == [1, 3, 4]


# --- workers that die -------------------------------------------------------


async def test_a_worker_cancelled_in_its_handler_hands_over_the_backlog() -> None:
    bot = _Bot()
    workers: list[asyncio.Task] = []

    async def stuck(_: object, message: Message) -> None:
        bot.handled.append(message.id)
        if message.id == 1:
            workers.append(asyncio.current_task())  # ty: ignore[invalid-argument-type]
            await asyncio.Event().wait()

    bot.on(stuck)
    async with _running(bot):
        bot.send(1, 2, 3)
        await _until(lambda: workers and bot.queued() == [2, 3])
        workers[0].cancel()
        await _until(lambda: len(bot.handled) == 3)
        await bot.settle()
        bot.dispatcher.handler_worker_tasks.remove(workers[0])

    assert bot.handled == [1, 2, 3]


# --- handlers ---------------------------------------------------------------


# --- with the rest of the library -------------------------------------------


async def test_reject_policy_refuses_the_wait_and_frees_the_key() -> None:
    bot = _Bot(workers=2, policy=WorkersPolicy.REJECT)
    busy: list[int] = []

    async def ask(_: object, message: Message) -> None:
        bot.handled.append(message.id)
        if message.id in (1, 2):
            try:
                await bot.listener.listen(MessageKey(CHAT, message.from_user.id), timeout=5)
            except ListenerWorkersBusy:
                busy.append(message.id)

    bot.on(ask)
    async with _running(bot):
        bot.send(1)
        await _until(lambda: bot.listener.listeners)
        bot.send(2, user=8)
        await _until(lambda: busy == [2])
        bot.send(3, user=8)
        await _until(lambda: 3 in bot.handled)
        bot.send(4)
        await bot.settle()

    assert bot.handled == [1, 2, 3]


async def test_cancel_oldest_ends_the_wait_and_runs_its_backlog() -> None:
    bot = _Bot(workers=2, policy=WorkersPolicy.CANCEL_OLDEST)
    evicted: list[int] = []
    second = asyncio.Event()

    async def ask(_: object, message: Message) -> None:
        bot.handled.append(message.id)
        if message.id == 1:
            try:
                await bot.ask(filters=_ids(99))
            except ListenerEvicted:
                evicted.append(message.id)
        elif message.id == 3:
            await bot.listener.listen(MessageKey(CHAT, 8), timeout=5)
            second.set()

    bot.on(ask)
    async with _running(bot):
        bot.send(1)
        await _until(lambda: bot.listener.listeners)
        bot.send(2)
        await _until(lambda: bot.queued() == [2])
        bot.send(3, user=8)
        await _until(lambda: evicted)
        await _until(lambda: 2 in bot.handled)
        bot.send(4, user=8)
        await _until(second.is_set)
        await bot.settle()


async def test_a_replaced_wait_ends_its_handler_and_frees_the_key() -> None:
    bot = _Bot()
    outcomes: list[object] = []

    async def ask(_: object, message: Message) -> None:
        bot.handled.append(message.id)
        if message.id == 1:
            try:
                await bot.listener.listen(MessageKey(CHAT), timeout=5, filters=_ids(99))
            except ListenerReplaced:
                outcomes.append("replaced")
        elif message.id == 3:
            outcomes.append(
                (await bot.listener.listen(MessageKey(CHAT), timeout=5, filters=_ids(4))).id
            )

    bot.on(ask)
    async with _running(bot):
        bot.send(1)
        await _until(lambda: bot.listener.listeners)
        bot.send(2)
        await _until(lambda: bot.queued() == [2])
        bot.send(3, user=8)
        await _until(lambda: "replaced" in outcomes)
        await _until(lambda: 2 in bot.handled)
        bot.send(4, user=9)
        await _until(lambda: 4 in outcomes)
        await bot.settle()

    assert outcomes == ["replaced", 4]


async def test_a_cancelled_wait_ends_its_handler_and_frees_the_key() -> None:
    bot = _Bot()
    outcomes: list[str] = []

    async def ask(_: object, message: Message) -> None:
        bot.handled.append(message.id)
        if message.id == 1:
            try:
                await bot.ask(filters=_ids(99))
            except ListenerCancelled:
                outcomes.append("cancelled")

    bot.on(ask)
    async with _running(bot):
        bot.send(1)
        await _until(lambda: bot.listener.listeners)
        bot.send(2)
        await _until(lambda: bot.queued() == [2])
        bot.listener.cancel(MessageKey(CHAT, USER))
        await _until(lambda: 2 in bot.handled)
        await bot.settle()

    assert outcomes == ["cancelled"]


# --- note_handler_wait and listen -------------------------------------------------


async def test_listen_drops_the_hold_from_its_frame_once_the_wait_fails() -> None:
    # The traceback of the error keeps the frame of `listen`, as in gotcha 12.
    hold = _HandlerHold(_Lane((0, CHAT)), 0)
    # Registered on the bot's client, so `listen` takes the hold.
    listener = _Bot().listener
    token = _HANDLER_HOLD.set(hold)
    try:
        waiter = asyncio.ensure_future(listener.listen(MessageKey(CHAT)))
        await asyncio.sleep(0)
    finally:
        _HANDLER_HOLD.reset(token)

    listener.cancel(MessageKey(CHAT))
    with pytest.raises(ListenerCancelled) as caught:
        await waiter

    frames = [entry.frame for entry in caught.traceback if entry.name == "listen"]

    assert frames
    assert all("hold" not in frame.f_locals for frame in frames)


async def test_a_hold_keeps_no_declined_update_alive() -> None:
    bot = _Bot(key=by_chat)

    async def ask(_: object, message: Message) -> None:
        bot.handled.append(message.id)
        if message.id == 1:
            with pytest.raises(ListenerCancelled):
                await bot.ask(user=None, filters=_ids(99))

    bot.on(ask)
    async with _running(bot):
        bot.send(1)
        await _until(lambda: bot.listener.listeners)
        hold = bot.dispatcher.lanes_by_key[(0, CHAT)].handler_hold
        assert hold is not None
        bot.send(2)
        await _until(lambda: len(hold.declined_by_handler_waits) == 1)
        bot.listener.cancel(MessageKey(CHAT))
        await _until(lambda: 2 in bot.handled)
        await bot.settle()

    # Once stopped: an idle worker keeps its last update in a local, as Pyrogram's does.
    gc.collect()

    assert len(hold.declined_by_handler_waits) == 0


# --- turns ------------------------------------------------------------------


# --- stopping and restarting ------------------------------------------------


async def test_stop_runs_the_backlog_before_the_workers_exit() -> None:
    bot = _Bot()
    release = asyncio.Event()

    async def record(_: object, message: Message) -> None:
        bot.handled.append(message.id)
        if message.id == 1:
            await release.wait()

    bot.on(record)
    await bot.dispatcher.start()
    bot.send(1, 2, 3)
    await _until(lambda: bot.queued() == [2, 3])

    stopping = asyncio.ensure_future(bot.dispatcher.stop())
    await asyncio.sleep(0.01)
    release.set()
    await asyncio.wait_for(stopping, 5)

    assert bot.handled == [1, 2, 3]
    assert bot.dispatcher.lanes_by_key == {}


async def test_stop_ends_a_held_wait_and_the_backlog_runs_with_its_waits_refused() -> None:
    bot = _Bot()
    outcomes: list[int] = []

    async def ask(_: object, message: Message) -> None:
        bot.handled.append(message.id)
        try:
            await bot.ask(filters=_ids(99))
        except ListenerCancelled:
            outcomes.append(message.id)

    bot.on(ask)
    await bot.dispatcher.start()
    bot.send(1)
    await _until(lambda: bot.listener.listeners)
    bot.send(2)
    await _until(lambda: bot.queued() == [2])

    await asyncio.wait_for(bot.dispatcher.stop(), 5)

    assert outcomes == [1, 2]
    assert bot.dispatcher.lanes_by_key == {}


async def test_a_restart_keeping_the_handlers_serves_the_same_key_again() -> None:
    bot = _Bot()

    async def record(_: object, message: Message) -> None:
        bot.handled.append(message.id)

    bot.on(record)
    await bot.dispatcher.start()
    bot.send(1)
    await _until(lambda: bot.handled)
    await asyncio.wait_for(bot.dispatcher.stop(clear_handlers=False), 5)

    await bot.dispatcher.start()
    bot.send(2)
    await _until(lambda: len(bot.handled) == 2)
    await bot.settle()
    await asyncio.wait_for(bot.dispatcher.stop(), 5)

    assert bot.handled == [1, 2]


async def test_no_hold_is_set_with_the_base_dispatcher(caplog: pytest.LogCaptureFixture) -> None:
    client = _bare_client(workers=1)
    seen: list[object] = []

    async def probe(_: object, message: Message) -> None:
        seen.append(_HANDLER_HOLD.get())

    client.dispatcher.update_parsers[_Packet] = _Bot.parse
    client.add_handler(MessageHandler(probe))
    await client.dispatcher.start()
    client.dispatcher.updates_queue.put_nowait((_Packet(make_message(), MessageHandler), {}, {}))  # ty: ignore[invalid-argument-type]
    await _until(lambda: seen)
    await asyncio.wait_for(client.dispatcher.stop(), 5)

    assert seen == [None]
    assert caplog.records == [] or all(r.levelno < logging.ERROR for r in caplog.records)


# --- reading and parsing ----------------------------------------------------


class _SlowParse:
    """A raw update stand-in whose parsing waits for `gate`, or fails."""

    def __init__(
        self, parsed: object, gate: asyncio.Event | None = None, fail: bool = False
    ) -> None:
        self.parsed, self.gate, self.fail = parsed, gate, fail


async def _parse_slow(update: _SlowParse, users: object, chats: object) -> tuple[object, type]:
    if update.gate is not None:
        await update.gate.wait()
    if update.fail:
        msg = "cannot parse"
        raise ValueError(msg)
    return update.parsed, MessageHandler


def _send_slow(bot: _Bot, update: _SlowParse) -> None:
    bot.dispatcher.update_parsers[_SlowParse] = _parse_slow
    bot.dispatcher.updates_queue.put_nowait((update, {}, {}))  # ty: ignore[invalid-argument-type]


def _recorder(bot: _Bot) -> None:
    async def record(_: object, message: Message) -> None:
        bot.handled.append(message.id)

    bot.on(record)


async def test_an_update_that_parses_late_still_runs_first() -> None:
    bot = _Bot()
    _recorder(bot)
    gate = asyncio.Event()
    async with _running(bot):
        _send_slow(bot, _SlowParse(make_message(CHAT, USER, 1), gate))
        _send_slow(bot, _SlowParse(make_message(CHAT, USER, 2)))
        await asyncio.sleep(0.02)
        assert bot.handled == []

        gate.set()
        await _until(lambda: len(bot.handled) == 2)

    assert bot.handled == [1, 2]


async def test_an_update_that_fails_to_parse_blocks_nothing(
    caplog: pytest.LogCaptureFixture,
) -> None:
    bot = _Bot()
    _recorder(bot)
    with caplog.at_level(logging.ERROR, logger=coordinated_module.log.name):
        async with _running(bot):
            _send_slow(bot, _SlowParse(make_message(CHAT, USER, 1), fail=True))
            bot.send(2)
            await _until(lambda: bot.handled)

    assert bot.handled == [2]
    assert "Error parsing an update" in caplog.text


async def test_a_raw_update_with_no_parser_reaches_raw_handlers() -> None:
    bot = _Bot()
    seen: list[object] = []

    async def raw_handler(_: object, update: object, __: object, ___: object) -> None:
        seen.append(update)

    bot.client.add_handler(RawUpdateHandler(raw_handler))
    raw = object()
    async with _running(bot):
        bot.dispatcher.updates_queue.put_nowait((raw, {}, {}))  # ty: ignore[invalid-argument-type]
        await _until(lambda: seen)

    assert seen == [raw]


async def test_the_reader_reads_no_more_than_workers_ahead() -> None:
    bot = _Bot(workers=2)
    gate = asyncio.Event()
    async with _running(bot):
        for number in range(5):
            _send_slow(bot, _SlowParse(make_message(CHAT, USER + number, number), gate))
        await asyncio.sleep(0.02)

        assert bot.dispatcher.updates_queue.qsize() == 3

        gate.set()
        await bot.settle()


async def test_nothing_internal_is_written_to_the_updates_queue() -> None:
    bot = _Bot()
    written: list[object] = []
    queue = bot.dispatcher.updates_queue
    put = queue.put_nowait

    def spy(item: Any) -> None:
        written.append(item)
        put(item)

    queue.put_nowait = spy  # ty: ignore[invalid-assignment]

    async def ask(_: object, message: Message) -> None:
        if message.id == 1:
            await bot.ask()

    bot.on(ask)
    async with _running(bot):
        bot.send(1, 2, 3)
        await bot.settle()

    assert all(item is None or isinstance(item[0], _Packet) for item in written)  # ty: ignore[index,not-subscriptable]


async def test_no_reader_runs_with_no_updates() -> None:
    bot = _Bot()
    bot.client.no_updates = True

    await bot.dispatcher.start()

    assert bot.dispatcher.reader_task is None
    await asyncio.wait_for(bot.dispatcher.stop(), 5)


async def test_a_new_user_is_not_kept_behind_a_flood() -> None:
    # The worker left free parses the flood into its lane while the first handler runs.
    bot = _Bot(workers=2, key=by_user)
    order: list[tuple[int, int]] = []

    async def record(_: object, message: Message) -> None:
        order.append((message.from_user.id, message.id))
        # An instant handler ends before the reader has queued anything behind it.
        await asyncio.sleep(0.01)

    bot.on(record)
    bot.send(1, 2, 3, user=USER)
    bot.send(4, user=8)
    async with _running(bot):
        await bot.settle()

    assert order.index((8, 4)) < order.index((USER, 3))


async def test_without_a_policy_a_reply_is_parsed_only_once_a_worker_is_free() -> None:
    bot = _Bot(workers=1)
    outcomes: list[str] = []

    async def ask(_: object, message: Message) -> None:
        if message.id != 1:
            bot.handled.append(message.id)
            return
        with pytest.raises(ListenerTimeout):
            await bot.ask(timeout=0.05)
        outcomes.append("timed out")

    bot.on(ask)
    async with _running(bot):
        bot.send(1)
        await _until(lambda: bot.listener.listeners)
        bot.send(2)
        await _until(lambda: bot.handled)

    assert (outcomes, bot.replies, bot.handled) == (["timed out"], [], [2])


# --- what running the offers apart from the wait fixes ----------------------


async def test_a_filter_that_opens_a_wait_does_not_freeze_the_key() -> None:
    bot = _Bot()
    inner: list[str] = []

    async def waiting_filter(_: object, __: object, update: Message) -> bool:
        with pytest.raises(ListenerTimeout):
            await bot.listener.listen(MessageKey(CHAT, USER + 1), timeout=0.01)
        inner.append("ended")
        return False

    async def ask(_: object, message: Message) -> None:
        bot.handled.append(message.id)
        if message.id == 1:
            await asyncio.sleep(0.02)  # message 2 is queued before the wait starts
            with pytest.raises(ListenerTimeout):
                await bot.ask(filters=filters.create(waiting_filter), timeout=0.05)

    bot.on(ask)
    async with _running(bot):
        bot.send(1, 2)
        await _until(lambda: bot.handled == [1, 2])

    assert inner == ["ended"]


async def test_a_timeout_is_not_held_up_by_a_slow_filter() -> None:
    bot = _Bot()
    gate = asyncio.Event()
    inside: list[int] = []
    outcome: list[str] = []

    async def ask(_: object, message: Message) -> None:
        if message.id == 1:
            await asyncio.sleep(0.02)
            try:
                await bot.ask(filters=_paused(gate, inside), timeout=0.01)
            except ListenerTimeout:
                outcome.append("timeout")

    bot.on(ask)
    async with _running(bot):
        bot.send(1, 2)
        await _until(lambda: outcome, timeout=1)  # the gate is still closed
        gate.set()


async def test_a_cancelled_wait_leaves_the_offers_running() -> None:
    bot = _Bot()
    gate = asyncio.Event()
    inside: list[int] = []
    cut: list[bool] = []
    results: list[object] = []

    async def ask(_: object, message: Message) -> None:
        if message.id != 1:
            return

        first = asyncio.ensure_future(bot.ask(user=USER, filters=_ids(3), timeout=3))
        # Started together, so neither inherits what the other declines.
        second = asyncio.ensure_future(bot.ask(user=None, filters=_paused(gate, inside)))
        await _until(lambda: inside)
        second.cancel()
        with pytest.raises(asyncio.CancelledError):
            await second
        cut.append(True)
        results.append(await first)

    bot.on(ask)
    async with _running(bot):
        bot.send(1, 2)
        await _until(lambda: inside)
        bot.send(3)
        await _until(lambda: cut)
        gate.set()
        await _until(lambda: results, timeout=3)

    assert results == [3]


async def test_offers_run_outside_the_hold() -> None:
    bot = _Bot()
    holds: list[object] = []

    async def see_hold(_: object, __: object, update: Message) -> bool:
        holds.append(_HANDLER_HOLD.get())
        return True

    async def ask(_: object, message: Message) -> None:
        if message.id == 1:
            await asyncio.sleep(0.02)
            await bot.ask(filters=filters.create(see_hold))

    bot.on(ask)
    async with _running(bot):
        bot.send(1, 2)
        await _until(lambda: bot.replies)

    assert holds == [None]


async def test_listen_returns_a_queued_reply_with_the_handler_still_running() -> None:
    bot = _Bot()

    async def ask(_: object, message: Message) -> None:
        if message.id == 1:
            await asyncio.sleep(0.02)
            bot.handled.append(await bot.ask())

    bot.on(ask)
    async with _running(bot):
        bot.send(1, 2)
        await _until(lambda: bot.handled)

    assert bot.handled == [2]


# --- Pyrogram's propagation rules -------------------------------------------


async def test_continue_propagation_goes_on_to_the_next_handler() -> None:
    bot = _Bot()
    seen: list[str] = []

    async def first(_: object, message: Message) -> None:
        seen.append("first")
        raise ContinuePropagation

    async def second(_: object, message: Message) -> None:
        seen.append("second")

    bot.on(first)
    bot.on(second)
    async with _running(bot):
        bot.send(1)
        await bot.settle()

    assert seen == ["first", "second"]


async def test_stop_propagation_ends_the_other_groups() -> None:
    bot = _Bot()
    seen: list[str] = []

    async def first(_: object, message: Message) -> None:
        seen.append("first")
        raise StopPropagation

    async def second(_: object, message: Message) -> None:
        seen.append("second")

    bot.on(first, group=0)
    bot.on(second, group=1)
    async with _running(bot):
        bot.send(1)
        await bot.settle()

    assert seen == ["first"]


# --- under load -------------------------------------------------------------


def _parse_jittered(rng: random.Random) -> Callable[..., Any]:
    async def parse(update: _SlowParse, users: object, chats: object) -> tuple[object, type]:
        for _ in range(rng.randrange(4)):
            await asyncio.sleep(0)
        return update.parsed, MessageHandler

    return parse


@pytest.mark.parametrize("drip", [False, True], ids=["burst", "drip"])
@pytest.mark.parametrize("workers", [1, 2, 8])
@pytest.mark.parametrize("seed", [1, 2, 3])
async def test_load_keeps_order_and_exclusion_and_loses_nothing(
    drip: bool, workers: int, seed: int
) -> None:
    rng = random.Random(seed)
    bot = _Bot(workers=workers, key=by_user)
    running: dict[int, int] = {}
    peak: dict[int, int] = {}
    order: dict[int, list[int]] = {}
    sent: dict[int, list[int]] = {}

    async def record(_: object, message: Message) -> None:
        user = message.from_user.id
        running[user] = running.get(user, 0) + 1
        peak[user] = max(peak.get(user, 0), running[user])
        try:
            await asyncio.sleep(rng.choice((0, 0, 0.001)))
            order.setdefault(user, []).append(message.id)
        finally:
            running[user] -= 1

    bot.on(record)
    bot.dispatcher.update_parsers[_SlowParse] = _parse_jittered(rng)
    async with _running(bot):
        for number in range(300):
            user = rng.randrange(6)
            sent.setdefault(user, []).append(number)
            message = make_message(CHAT, user, number)
            bot.dispatcher.updates_queue.put_nowait((_SlowParse(message), {}, {}))  # ty: ignore[invalid-argument-type]
            if drip:
                await asyncio.sleep(0)
        await bot.settle()

    assert order == sent
    assert set(peak.values()) == {1}
    assert bot.dispatcher.lanes_by_key == {}


# --- standing alone and stopping ---------------------------------------------


async def test_it_takes_nothing_from_the_dispatcher_it_replaces() -> None:
    client = _bare_client()
    listener = MessageListener()
    client.register_listener(listener)
    handler = MessageHandler(lambda *_: None)
    client.dispatcher.groups[1] = [handler]
    old = client.dispatcher
    packet = (_Packet(make_message(), MessageHandler), {}, {})
    old.updates_queue.put_nowait(packet)  # ty: ignore[invalid-argument-type]

    dispatcher = CoordinatedDispatcher(client, key_functions=[by_user])

    assert (dispatcher.listeners, dict(dispatcher.groups)) == ({}, {})
    assert dispatcher.updates_queue.empty()
    assert old.listeners == {Message: listener}
    assert old.groups == {1: [handler]}
    assert old.updates_queue.qsize() == 1


@pytest.mark.parametrize("backlog", [5, 30])
async def test_stop_with_a_backlog_behind_a_running_handler_ends(backlog: int) -> None:
    bot = _Bot()

    async def slow(_: object, message: Message) -> None:
        bot.handled.append(message.id)
        await asyncio.sleep(0.005)

    bot.on(slow)
    await bot.dispatcher.start()
    bot.send(1)
    await _until(lambda: bot.handled)
    bot.send(*range(2, backlog + 2))

    await asyncio.wait_for(bot.dispatcher.stop(), 5)

    assert bot.handled == list(range(1, backlog + 2))


async def test_stop_waits_for_an_update_still_parsing() -> None:
    bot = _Bot()
    _recorder(bot)
    gate = asyncio.Event()
    await bot.dispatcher.start()
    _send_slow(bot, _SlowParse(make_message(CHAT, USER, 1), gate))
    _send_slow(bot, _SlowParse(make_message(CHAT, USER, 2)))
    await asyncio.sleep(0.01)

    stopping = asyncio.ensure_future(bot.dispatcher.stop())
    await asyncio.sleep(0.01)
    assert not stopping.done()

    gate.set()
    await asyncio.wait_for(stopping, 5)

    assert bot.handled == [1, 2]


def test_init_orders_the_arrivals_for_the_workers_of_the_client() -> None:
    bot = _Bot(workers=4)

    assert bot.dispatcher.arrival_order.numbers_given == 0
    assert bot.dispatcher.arrival_order.read_slots._value == 4


async def test_start_opens_a_new_arrival_order() -> None:
    bot = _Bot()
    arrival_order = bot.dispatcher.arrival_order

    await bot.dispatcher.start()

    assert bot.dispatcher.arrival_order is not arrival_order
    await asyncio.wait_for(bot.dispatcher.stop(), 5)


async def test_start_opens_a_new_run() -> None:
    bot = _Bot()
    ready = bot.dispatcher.worker_instructions

    await bot.dispatcher.start()

    assert bot.dispatcher.worker_instructions is not ready
    await asyncio.wait_for(bot.dispatcher.stop(), 5)


async def test_the_workers_run_until_the_dispatcher_stops() -> None:
    bot = _Bot(workers=2)
    await bot.dispatcher.start()
    await asyncio.sleep(0.01)

    assert len(bot.dispatcher.handler_worker_tasks) == 2

    await asyncio.wait_for(bot.dispatcher.stop(), 5)

    assert bot.dispatcher.handler_worker_tasks == []


async def test_a_worker_survives_an_error_outside_the_handlers(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    bot = _Bot(workers=1)

    async def fail(_: object, message: Message) -> None:
        bot.handled.append(message.id)
        msg = "handler failed"
        raise ValueError(msg)

    async def broken(*_: object) -> None:
        msg = "error handling failed"
        raise RuntimeError(msg)

    monkeypatch.setattr(bot.dispatcher, "handle_update_handler_exception", broken)
    bot.on(fail)
    with caplog.at_level(logging.ERROR, logger=coordinated_module.log.name):
        async with _running(bot):
            bot.send(1, 2)
            await _until(lambda: len(bot.handled) == 2)

    assert "Unexpected error in handler_worker" in caplog.text


async def test_workers_count_themselves_before_a_backlog_at_start() -> None:
    bot = _Bot(workers=2, policy=WorkersPolicy.REJECT)
    errors: list[Exception] = []

    async def ask(_: object, message: Message) -> None:
        try:
            await bot.ask(timeout=0.01)
        except ListenerTimeout:
            bot.handled.append(message.id)
        except Exception as exc:
            errors.append(exc)

    bot.on(ask)
    bot.send(1)
    async with _running(bot):
        await _until(lambda: bot.handled or errors)

    assert errors == []


async def test_a_coordinated_worker_clears_an_inherited_handler_hold() -> None:
    seen: list[object] = []

    class Spy(MessageListener):
        async def resolve(self, update: Message) -> bool:
            seen.append(_HANDLER_HOLD.get())
            return await super().resolve(update)

    bot = _Bot(listener=Spy())
    token = _HANDLER_HOLD.set(object())  # ty: ignore[invalid-argument-type]
    try:
        await bot.dispatcher.start()
    finally:
        _HANDLER_HOLD.reset(token)

    bot.send(1)
    await bot.settle()
    await asyncio.wait_for(bot.dispatcher.stop(), 5)

    assert seen == [None]


# --- who parses, and how many tasks ------------------------------------------


async def test_the_workers_parse_and_each_update_adds_no_task() -> None:
    bot = _Bot(workers=2)
    parsed_by: list[asyncio.Task | None] = []
    during: list[int] = []

    async def parse(update: _Packet, users: object, chats: object) -> tuple[object, type]:
        parsed_by.append(asyncio.current_task())
        during.append(len(asyncio.all_tasks()))
        return update.parsed, update.handler_type

    bot.dispatcher.update_parsers[_Packet] = parse
    _recorder(bot)

    async with _running(bot):
        await asyncio.sleep(0.01)
        reader = bot.dispatcher.reader_task
        workers = set(bot.dispatcher.handler_worker_tasks)
        before = len(asyncio.all_tasks())
        bot.send(*range(1, 51))
        await _until(lambda: len(bot.handled) == 50)

    assert reader not in parsed_by
    assert set(parsed_by) <= workers
    assert max(during) == before


async def test_with_a_policy_the_worker_left_free_parses_the_reply() -> None:
    bot = _Bot(workers=2, policy=WorkersPolicy.REJECT)
    parsed_by: list[asyncio.Task | None] = []
    asking: list[asyncio.Task | None] = []

    async def parse(update: _Packet, users: object, chats: object) -> tuple[object, type]:
        parsed_by.append(asyncio.current_task())
        return update.parsed, update.handler_type

    async def ask(_: object, message: Message) -> None:
        if message.id == 1:
            asking.append(asyncio.current_task())
            await bot.ask()

    bot.dispatcher.update_parsers[_Packet] = parse
    bot.on(ask)

    async with _running(bot):
        workers = set(bot.dispatcher.handler_worker_tasks)
        bot.send(1)
        await _until(lambda: bot.dispatcher.listeners[Message].listeners)
        bot.send(2)
        await _until(lambda: bot.replies)

    assert bot.replies == [2]
    assert parsed_by[-1] in workers
    assert parsed_by[-1] is not asking[0]


async def test_a_flood_behind_a_waiting_handler_does_not_block_its_reply() -> None:
    bot = _Bot(workers=2, policy=WorkersPolicy.REJECT)

    async def ask(_: object, message: Message) -> None:
        if message.id == 1:
            await bot.ask()
        bot.handled.append(message.id)

    bot.on(ask)

    async with _running(bot):
        bot.send(*range(1, 201))
        await _until(lambda: len(bot.handled) == 199)

    assert bot.replies == [2]
    assert bot.handled == [1, *range(3, 201)]


async def test_the_offer_task_clears_an_inherited_handler_hold() -> None:
    seen: list[object] = []

    class Spy(MessageListener):
        async def resolve(self, update: Message) -> bool:
            seen.append(_HANDLER_HOLD.get())
            return await super().resolve(update)

    bot = _Bot(listener=Spy())

    async def ask(_: object, message: Message) -> None:
        if message.id == 1:
            await asyncio.sleep(0.01)
            await bot.ask()

    bot.on(ask)
    token = _HANDLER_HOLD.set(object())  # ty: ignore[invalid-argument-type]
    try:
        await bot.dispatcher.start()
    finally:
        _HANDLER_HOLD.reset(token)

    bot.send(1, 2)
    await _until(lambda: bot.replies)
    await asyncio.wait_for(bot.dispatcher.stop(), 5)

    assert len(seen) >= 2
    assert set(seen) == {None}


async def test_stop_ends_the_offer_task() -> None:
    bot = _Bot()
    before = asyncio.all_tasks()
    await bot.dispatcher.start()

    await asyncio.wait_for(bot.dispatcher.stop(), 5)
    await asyncio.sleep(0)

    assert asyncio.all_tasks() == before


# --- the count, and the placing of an update ------------------------------------


def _reading(bot: _Bot) -> CoordinatedDispatcher:
    """Set up what `start` sets up, so `_parse_and_place` can run with no workers."""
    bot.dispatcher.unfinished_updates = ZeroWaitCounter()
    bot.dispatcher.arrival_order = ArrivalOrder(1)
    return bot.dispatcher


async def _parse_one(
    dispatcher: CoordinatedDispatcher, parsed: object, handler_type: type = MessageHandler
) -> None:
    """Read, parse and place one update as the reader and a worker would."""
    arrival_order = dispatcher.arrival_order
    await arrival_order.read_slots.acquire()
    raw_update = (_Packet(parsed, handler_type), {}, {})
    update_to_parse = _UpdateToParse(arrival_order.give_next_number(), raw_update)  # ty: ignore[invalid-argument-type]
    await dispatcher._parse_and_place(update_to_parse)


async def test_async_counter_wait_ends_when_the_count_is_back_at_zero() -> None:
    counter = ZeroWaitCounter()
    await asyncio.wait_for(counter.wait_until_zero(), 1)
    counter.increment()
    counter.increment()
    waiter = asyncio.ensure_future(counter.wait_until_zero())

    counter.decrement()
    await asyncio.sleep(0)
    assert not waiter.done()

    counter.decrement()
    await asyncio.wait_for(waiter, 1)


def _to_parse(arrival_order: ArrivalOrder, update: object) -> _UpdateToParse:
    raw_update = (update, {}, {})
    return _UpdateToParse(arrival_order.give_next_number(), raw_update)  # ty: ignore[invalid-argument-type]


def test_arrival_order_gives_numbers_in_turn() -> None:
    arrival_order = ArrivalOrder(2)

    assert [arrival_order.give_next_number() for _ in range(3)] == [0, 1, 2]
    assert not arrival_order.all_admitted.is_set()


def test_arrival_order_admits_in_the_order_numbered() -> None:
    arrival_order = ArrivalOrder(2)
    first, second = make_entry(), make_entry()
    arrival_order.give_next_number()
    arrival_order.give_next_number()

    assert arrival_order.admit_in_order(1, second) == []
    assert arrival_order.admit_in_order(0, first) == [first, second]
    assert arrival_order.all_admitted.is_set()


def test_arrival_order_skips_an_update_that_failed_to_parse() -> None:
    arrival_order = ArrivalOrder(2)
    entry = make_entry()
    arrival_order.give_next_number()
    arrival_order.give_next_number()

    assert arrival_order.admit_in_order(0, None) == []
    assert arrival_order.admit_in_order(1, entry) == [entry]


async def test_arrival_order_frees_a_read_slot_per_update_admitted() -> None:
    arrival_order = ArrivalOrder(1)
    await arrival_order.read_slots.acquire()
    arrival_order.give_next_number()

    assert arrival_order.read_slots.locked()

    arrival_order.admit_in_order(0, make_entry())

    assert not arrival_order.read_slots.locked()


async def test_arrival_order_wait_ends_once_all_are_admitted() -> None:
    arrival_order = ArrivalOrder(1)
    await asyncio.wait_for(arrival_order.wait_until_all_admitted(), 1)
    arrival_order.give_next_number()
    waiter = asyncio.ensure_future(arrival_order.wait_until_all_admitted())

    await asyncio.sleep(0)
    assert not waiter.done()

    arrival_order.admit_in_order(0, None)
    await asyncio.wait_for(waiter, 1)


async def test_parse_places_the_updates_in_the_order_read() -> None:
    dispatcher = _reading(_Bot())
    arrival_order = dispatcher.arrival_order = ArrivalOrder(2)
    first = _to_parse(arrival_order, _Packet(make_message(CHAT, USER, 1), MessageHandler))
    second = _to_parse(arrival_order, _Packet(make_message(CHAT, USER + 1, 2), MessageHandler))

    await dispatcher._parse_and_place(second)

    assert dispatcher.worker_instructions.empty()

    await dispatcher._parse_and_place(first)

    assert dispatcher.worker_instructions.get_nowait().parsed_update.id == 1
    assert dispatcher.worker_instructions.get_nowait().parsed_update.id == 2


async def test_a_cancelled_parse_still_queues_what_is_due_behind_it() -> None:
    dispatcher = _reading(_Bot())
    arrival_order = dispatcher.arrival_order = ArrivalOrder(2)
    dispatcher.update_parsers[_SlowParse] = _parse_slow
    first = _to_parse(arrival_order, _SlowParse(make_message(CHAT, USER, 1), asyncio.Event()))
    second = _to_parse(arrival_order, _Packet(make_message(CHAT, USER + 1, 2), MessageHandler))
    parse_first = asyncio.ensure_future(dispatcher._parse_and_place(first))
    await asyncio.sleep(0)
    await dispatcher._parse_and_place(second)
    parse_first.cancel()

    with pytest.raises(asyncio.CancelledError):
        await parse_first

    assert dispatcher.worker_instructions.get_nowait().parsed_update.id == 2
    assert arrival_order.all_admitted.is_set()


async def test_parse_posts_the_first_update_of_a_lane_and_queues_the_next() -> None:
    bot = _Bot()
    dispatcher = _reading(bot)

    await _parse_one(dispatcher, make_message(CHAT, USER, 1))
    await _parse_one(dispatcher, make_message(CHAT, USER, 2))

    posted = dispatcher.worker_instructions.get_nowait()
    assert posted.parsed_update.id == 1
    assert posted.lane.turn_taken is True
    assert dispatcher.worker_instructions.empty()
    assert bot.queued() == [2]
    assert dispatcher.unfinished_updates._count == 2


async def test_parse_has_an_update_behind_a_running_handler_offered() -> None:
    dispatcher = _reading(_Bot())
    await _parse_one(dispatcher, make_message(CHAT, USER, 1))
    hold = _open_hold(dispatcher, dispatcher.worker_instructions.get_nowait())

    await _parse_one(dispatcher, make_message(CHAT, USER, 2))

    assert dispatcher.offer_pass_requests.get_nowait() is hold


async def test_parse_runs_free_an_update_with_no_parsed_form() -> None:
    dispatcher = _reading(_Bot())

    await _parse_one(dispatcher, None, type(None))

    assert dispatcher.worker_instructions.get_nowait().lane is None
    assert dispatcher.unfinished_updates._count == 1


async def test_parse_runs_free_an_update_with_no_key() -> None:
    dispatcher = _reading(_Bot(key=lambda _: None))

    await _parse_one(dispatcher, make_message(CHAT, USER, 1))

    assert dispatcher.worker_instructions.get_nowait().lane is None


async def test_parse_drops_an_update_whose_parser_fails() -> None:
    dispatcher = _reading(_Bot())

    async def fail(*_: object) -> None:
        raise ValueError

    dispatcher.update_parsers[_Packet] = fail

    await _parse_one(dispatcher, make_message(CHAT, USER, 1))

    assert dispatcher.worker_instructions.empty()
    assert dispatcher.unfinished_updates._count == 0


@pytest.mark.parametrize(("took", "left"), [(True, 0), (False, 1)])
async def test_handle_listen_counts_only_a_taken_update_as_over(
    monkeypatch: pytest.MonkeyPatch, took: bool, left: int
) -> None:
    dispatcher = _reading(_Bot())
    dispatcher.unfinished_updates.increment()

    async def resolve(*_: object) -> bool:
        return took

    monkeypatch.setattr(Dispatcher, "handle_listen", resolve)

    assert await dispatcher.handle_listen(make_message(CHAT, USER, 1)) is took
    assert dispatcher.unfinished_updates._count == left


async def test_handle_update_counts_the_update_as_over_even_if_it_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dispatcher = _reading(_Bot())
    dispatcher.unfinished_updates.increment()

    async def run(*_: object) -> None:
        raise StopPropagation

    monkeypatch.setattr(Dispatcher, "handle_update", run)

    with pytest.raises(StopPropagation):
        await dispatcher.handle_update(("raw", {}, {}), None, type(None))

    assert dispatcher.unfinished_updates._count == 0


# --- the offer pass, run by the offer task --------------------------------------


def _by_chat() -> CoordinatedDispatcher:
    """A dispatcher with a lane per chat, not started."""
    return _Bot(key=sequencing.chat_key).dispatcher


async def _offer_pass(
    dispatcher: CoordinatedDispatcher,
    take: Collection[int] = (),
    during: Callable[[Any], object] | None = None,
) -> list[int]:
    """Run the offer task over the holds `offers` has, and return the ids it offered.

    Args:
        dispatcher: The dispatcher.
        take: The ids a wait takes.
        during: Called with each update while it is on offer.
    """
    offered: list[int] = []

    async def listen(update: Any) -> bool:
        offered.append(update.id)
        if during is not None:
            during(update)
        await asyncio.sleep(0)
        return update.id in take

    dispatcher.handle_listen = listen  # ty: ignore[invalid-assignment]
    dispatcher.offer_pass_requests.put_nowait(None)
    await dispatcher._run_offer_passes()
    return offered


async def test_offers_name_the_queue_in_order_once_per_generation() -> None:
    dispatcher = _by_chat()
    _, hold = _holding(dispatcher, make_entry(1), make_entry(2))

    assert await _offer_pass(dispatcher) == [1, 2]

    hold.request_offer_pass(dispatcher.offer_pass_requests)
    assert await _offer_pass(dispatcher) == []

    hold.note_handler_wait(dispatcher, sequencing.make_wait())
    assert await _offer_pass(dispatcher) == [1, 2]


async def test_offers_still_give_the_other_waits_what_the_waits_of_the_handler_declined() -> None:
    dispatcher = _by_chat()
    second = make_entry(1)
    _, hold = _holding(dispatcher, second)
    hold.on_handler_wait_declined(second.parsed_update)

    assert await _offer_pass(dispatcher) == [1]


def test_a_later_wait_of_the_handler_starts_with_what_its_waits_declined() -> None:
    dispatcher = _by_chat()
    _, hold = _holding(dispatcher)
    message = make_message()
    hold.on_handler_wait_declined(message)
    wait = sequencing.make_wait()

    hold.note_handler_wait(dispatcher, wait)

    assert wait.declined_updates[id(message)] is message


async def test_offers_stop_on_a_closed_hold() -> None:
    dispatcher = _by_chat()
    _, hold = _holding(dispatcher, make_entry(1))
    hold.lane.handler_hold = None  # the handler ended

    assert await _offer_pass(dispatcher) == []
    assert hold.offer_pass_active is False
    assert sequencing.drain_offers(dispatcher) == []


async def test_offers_skip_what_an_earlier_hold_offered_at_this_generation() -> None:
    dispatcher = _by_chat()
    second, third = make_entry(1), make_entry(2)
    first, _ = _holding(dispatcher, second, third)
    assert await _offer_pass(dispatcher) == [1, 2]
    assert first.lane is not None
    # What the worker does as the handler of `first` ends.
    first.lane.handler_hold = None
    dispatcher.worker_instructions.put_nowait(first.lane.waiting_updates.popleft())
    assert sequencing.take(dispatcher) is second

    _open_hold(dispatcher, second)

    assert await _offer_pass(dispatcher) == []


async def test_an_offer_taken_leaves_the_queue() -> None:
    dispatcher = _by_chat()
    first, hold = _holding(dispatcher, make_entry(1))

    assert await _offer_pass(dispatcher, take={1}) == [1]
    assert first.lane is not None
    assert list(first.lane.waiting_updates) == []
    assert hold.offer_pass_position == 0


async def test_an_offer_declined_moves_the_pass_on() -> None:
    dispatcher = _by_chat()
    second = make_entry(1)
    first, hold = _holding(dispatcher, second)

    assert await _offer_pass(dispatcher) == [1]
    assert first.lane is not None
    assert list(first.lane.waiting_updates) == [second]
    assert hold.offer_pass_position == 1


async def test_a_wait_starts_only_between_two_offers_and_gets_the_queue_from_its_head() -> None:
    dispatcher = _by_chat()
    _, hold = _holding(dispatcher, make_entry(1))
    events: list[str] = []
    starting: list[asyncio.Future] = []

    async def start_a_wait() -> None:
        # What `listen` does before it registers a wait.
        async with hold.offer_lock:
            pass
        hold.note_handler_wait(dispatcher, sequencing.make_wait())
        events.append("wait")

    def on_offer(_: object) -> None:
        events.append("offer")
        if not starting:
            starting.append(asyncio.ensure_future(start_a_wait()))

    assert await _offer_pass(dispatcher, during=on_offer) == [1, 1]
    assert events == ["offer", "wait", "offer"]


async def test_a_burst_scans_the_queue_once() -> None:
    dispatcher = _by_chat()
    _, hold = _holding(dispatcher)
    offered = 0

    for number in range(1, 200):
        _admit(dispatcher, make_entry(number))
        offered += len(await _offer_pass(dispatcher))

    assert offered == 199
    assert hold.offer_pass_position == 199


async def test_a_cancelled_pass_frees_its_hold() -> None:
    dispatcher = _by_chat()
    _, hold = _holding(dispatcher, make_entry(1))

    async def cut(_: object) -> bool:
        raise asyncio.CancelledError

    dispatcher.handle_listen = cut  # ty: ignore[invalid-assignment]

    with pytest.raises(asyncio.CancelledError):
        await dispatcher._run_offer_passes()

    assert hold.offer_pass_active is False
    assert not hold.offer_lock.locked()


# --- the worker closing the hold ------------------------------------------------


async def test_a_wait_that_takes_an_update_in_the_worker_frees_its_lane() -> None:
    bot = _Bot()

    async def record(_: object, message: Message) -> None:
        bot.handled.append(message.id)

    bot.on(record)

    async with _running(bot):
        waiting = asyncio.ensure_future(bot.ask())
        await _until(lambda: bot.listener.listeners)
        bot.send(1)
        await asyncio.wait_for(waiting, 1)
        bot.send(2)
        await bot.settle()

    assert (bot.replies, bot.handled) == ([1], [2])


async def test_a_handler_that_ends_during_an_offer_keeps_its_worker() -> None:
    gated = _GatedListener()
    gate, release = asyncio.Event(), asyncio.Event()
    bot = _Bot(workers=2, listener=gated)

    async def handler(_: object, message: Message) -> None:
        bot.handled.append(message.id)
        if message.id == 1:
            await release.wait()

    bot.on(handler)
    gated.before[2] = gate

    async with _running(bot):
        bot.send(1)
        await _until(lambda: bot.handled == [1])
        bot.send(2)
        await _until(lambda: 2 in gated.paused)
        release.set()
        await asyncio.sleep(0.01)

        assert len(bot.dispatcher.handler_worker_tasks) == 2

        del gated.before[2]
        gate.set()
        await bot.settle()

    assert bot.handled == [1, 2]


# --- the decisions on a hold -----------------------------------------------------


def _admit(dispatcher: CoordinatedDispatcher, *updates: _UpdateToRun) -> None:
    """Place `updates` in their chat's lanes as `_read_updates` does; the setup these tests need."""

    for update_to_run in updates:
        function_and_key = (0, sequencing.chat_key(update_to_run.parsed_update))
        lane = dispatcher.lanes_by_key.get(function_and_key)

        if lane is None:
            lane = dispatcher.lanes_by_key[function_and_key] = _Lane(function_and_key)

        update_to_run.lane = lane

        if lane is None:
            dispatcher.worker_instructions.put_nowait(update_to_run)
        elif not lane.turn_taken:
            lane.turn_taken = True
            dispatcher.worker_instructions.put_nowait(update_to_run)
        else:
            lane.waiting_updates.append(update_to_run)

            if lane.handler_hold is not None:
                lane.handler_hold.request_offer_pass(dispatcher.offer_pass_requests)


def _open_hold(dispatcher: CoordinatedDispatcher, update_to_run: Any) -> _HandlerHold:
    """Open the hold of `update_to_run` as a worker does before its handlers."""
    lane = update_to_run.lane
    assert lane is not None
    hold = lane.handler_hold = _HandlerHold(lane, dispatcher.wait_generation)
    hold.request_offer_pass(dispatcher.offer_pass_requests)
    return hold


def _holding(
    dispatcher: CoordinatedDispatcher, *queued: _UpdateToRun
) -> tuple[_UpdateToRun, _HandlerHold]:
    """Place a first update, open its hold as a worker does, then queue `queued` behind it."""
    first = make_entry(0)
    _admit(dispatcher, first)
    assert sequencing.take(dispatcher) is first
    hold = _open_hold(dispatcher, first)
    _admit(dispatcher, *queued)
    return first, hold


def test_request_offer_pass_queues_a_hold_with_a_backlog_once_until_its_pass_ends() -> None:
    dispatcher = _by_chat()
    _, hold = _holding(dispatcher)

    hold.request_offer_pass(dispatcher.offer_pass_requests)
    assert sequencing.drain_offers(dispatcher) == []

    hold.lane.waiting_updates.append(make_entry(1))
    hold.request_offer_pass(dispatcher.offer_pass_requests)
    hold.request_offer_pass(dispatcher.offer_pass_requests)

    assert sequencing.drain_offers(dispatcher) == [hold]
    assert hold.offer_pass_active is True


def test_on_handler_wait_declined_keeps_the_update_weakly() -> None:
    dispatcher = _by_chat()
    _, hold = _holding(dispatcher)
    message = make_message()

    hold.on_handler_wait_declined(message)

    assert hold.declined_by_handler_waits[id(message)] is message

    del message
    gc.collect()

    assert dict(hold.declined_by_handler_waits) == {}


def test_note_handler_wait_after_the_handler_ended_counts_for_nothing() -> None:
    dispatcher = _by_chat()
    _, hold = _holding(dispatcher)
    hold.lane.handler_hold = None  # the handler ended
    wait = sequencing.make_wait()

    hold.note_handler_wait(dispatcher, wait)

    assert dispatcher.wait_generation == 0
    assert wait.on_declined_update is None


def test_note_handler_wait_moves_the_generation_and_rewinds_the_offer_pass() -> None:
    dispatcher = _by_chat()
    _, hold = _holding(dispatcher)
    hold.offer_pass_position = 3
    wait = sequencing.make_wait()
    message = make_message()

    hold.note_handler_wait(dispatcher, wait)

    assert dispatcher.wait_generation == hold.last_wait_generation == 1
    assert hold.offer_pass_position == 0
    assert wait.on_declined_update is not None
    wait.on_declined_update(message)
    assert hold.declined_by_handler_waits[id(message)] is message


def test_note_handler_wait_asks_for_an_offer_pass_only_with_a_backlog() -> None:
    dispatcher = _by_chat()
    _, hold = _holding(dispatcher)

    hold.note_handler_wait(dispatcher, sequencing.make_wait())
    assert sequencing.drain_offers(dispatcher) == []

    _admit(dispatcher, make_entry(1))
    hold.offer_pass_active = False
    sequencing.drain_offers(dispatcher)
    hold.note_handler_wait(dispatcher, sequencing.make_wait())
    assert sequencing.drain_offers(dispatcher) == [hold]


# --- the worker opening the hold -------------------------------------------------


async def test_a_worker_opens_no_hold_for_an_update_that_runs_free() -> None:
    bot = _Bot(key=lambda _: None)
    holds: list[object] = []

    async def record(_: object, message: Message) -> None:
        holds.append(_HANDLER_HOLD.get())

    bot.on(record)

    async with _running(bot):
        bot.send(1)
        await bot.settle()

    assert holds == [None]


async def test_a_worker_opens_the_hold_at_the_current_wait_generation() -> None:
    bot = _Bot()
    holds: list[Any] = []

    async def record(_: object, message: Message) -> None:
        holds.append(_HANDLER_HOLD.get())

    bot.on(record)

    async with _running(bot):
        bot.dispatcher.wait_generation = 4
        bot.send(1)
        await bot.settle()

    assert holds[0].last_wait_generation == 4


async def test_a_worker_opening_a_hold_with_a_backlog_asks_for_an_offer_pass(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bot = _Bot()
    release = asyncio.Event()
    holds: dict[int, Any] = {}
    requested: list[object] = []
    request = _HandlerHold.request_offer_pass

    def record_request(self: _HandlerHold, offer_pass_requests: Any) -> None:
        if self.lane.waiting_updates:
            requested.append(self)
        request(self, offer_pass_requests)

    monkeypatch.setattr(_HandlerHold, "request_offer_pass", record_request)

    async def handler(_: object, message: Message) -> None:
        holds[message.id] = _HANDLER_HOLD.get()
        if message.id == 1:
            await release.wait()

    bot.on(handler)

    async with _running(bot):
        bot.send(1)
        await _until(lambda: 1 in holds)
        bot.send(2, 3)
        await _until(lambda: bot.queued() == [2, 3])
        requested.clear()
        release.set()
        await bot.settle()

    assert requested == [holds[2]]


# --- key functions and lanes -----------------------------------------------------


def _keyed(*functions: Any) -> CoordinatedDispatcher:
    """A dispatcher with `functions`, whose reader can run alone."""
    dispatcher = _reading(_Bot())
    dispatcher.key_functions = functions
    return dispatcher


async def _lane_of(dispatcher: CoordinatedDispatcher, update: object) -> _Lane | None:
    """Have the reader place `update`, and return the lane it gave it."""
    await _parse_one(dispatcher, update)

    if not dispatcher.worker_instructions.empty():
        return dispatcher.worker_instructions.get_nowait().lane

    return next(
        lane
        for lane in dispatcher.lanes_by_key.values()
        if lane.waiting_updates and lane.waiting_updates[-1].parsed_update is update
    )


def test_init_passes_the_other_arguments_to_dispatcher(monkeypatch: pytest.MonkeyPatch) -> None:
    received: list[tuple[tuple[object, ...], dict[str, object]]] = []
    original = Dispatcher.__init__

    def record(self: Dispatcher, client: object, *args: object, **kw: object) -> None:
        received.append((args, kw))
        original(self, client)

    client = _bare_client()
    monkeypatch.setattr(Dispatcher, "__init__", record)

    CoordinatedDispatcher(client, "extra", key_functions=[sequencing.chat_key], flag=True)

    assert received == [(("extra",), {"flag": True})]


def test_it_starts_with_its_key_functions_and_no_lane() -> None:
    dispatcher = CoordinatedDispatcher(_bare_client(), key_functions=[sequencing.chat_key])

    assert (dispatcher.key_functions, dispatcher.lanes_by_key) == ((sequencing.chat_key,), {})


async def test_start_forgets_the_lanes_and_the_wait_generation() -> None:
    bot = _Bot(key=sequencing.chat_key)
    bot.dispatcher.lanes_by_key[(0, CHAT)] = _Lane((0, CHAT))
    bot.dispatcher.wait_generation = 3
    requests = bot.dispatcher.offer_pass_requests

    async with _running(bot):
        assert bot.dispatcher.offer_pass_requests is not requests
        assert (bot.dispatcher.lanes_by_key, bot.dispatcher.wait_generation) == ({}, 0)


async def test_a_key_gives_one_lane() -> None:
    dispatcher = _keyed(sequencing.chat_key)

    first = await _lane_of(dispatcher, make_message(1))

    assert await _lane_of(dispatcher, make_message(1)) is first
    assert await _lane_of(dispatcher, make_message(2)) is not first


async def test_a_key_is_stored_under_its_function() -> None:
    dispatcher = _keyed(sequencing.chat_key)

    lane = await _lane_of(dispatcher, make_message(5))

    assert dispatcher.lanes_by_key == {(0, 5): lane}
    assert lane is not None and lane.key == (0, 5)


async def test_the_first_key_function_to_give_a_key_decides() -> None:
    dispatcher = _keyed(sequencing.user_key, sequencing.chat_key)

    await _lane_of(dispatcher, make_message(5, 7))

    assert list(dispatcher.lanes_by_key) == [(0, 7)]


async def test_a_none_key_passes_the_update_to_the_next_function() -> None:
    dispatcher = _keyed(sequencing.user_key, sequencing.chat_key)

    await _lane_of(dispatcher, make_message(5, from_user=None))

    assert list(dispatcher.lanes_by_key) == [(1, 5)]


async def test_keys_of_different_functions_do_not_mix() -> None:
    dispatcher = _keyed(lambda update: update.id if update.id == 5 else None, sequencing.chat_key)

    assert await _lane_of(dispatcher, make_message(9, message_id=5)) is not (
        await _lane_of(dispatcher, make_message(5, message_id=6))
    )


async def test_a_constant_key_shares_one_lane() -> None:
    chat_key = sequencing.chat_key
    dispatcher = _keyed(lambda update: "vip" if chat_key(update) in (1, 2) else None, chat_key)

    vip = await _lane_of(dispatcher, make_message(1))

    assert await _lane_of(dispatcher, make_message(2)) is vip
    assert await _lane_of(dispatcher, make_message(3)) is not vip


@pytest.mark.parametrize("functions", [[], [lambda _: None]])
async def test_an_update_with_no_key_stores_nothing(functions: list) -> None:
    dispatcher = _keyed(*functions)

    assert await _lane_of(dispatcher, make_message()) is None
    assert dispatcher.lanes_by_key == {}


@pytest.mark.parametrize("bad", [lambda _: 1 / 0, lambda _: []])
async def test_a_failing_key_is_logged_and_the_update_goes_to_the_next_function(
    bad: object, caplog: pytest.LogCaptureFixture
) -> None:
    dispatcher = _keyed(bad, sequencing.chat_key)

    with caplog.at_level(logging.ERROR, logger=coordinated_module.log.name):
        lane = await _lane_of(dispatcher, make_message(5))

    assert "the update goes to the next one" in caplog.text
    assert dispatcher.lanes_by_key == {(1, 5): lane}


async def test_a_failing_key_then_a_good_one_does_not_reuse_the_key_of_the_update_before() -> None:
    dispatcher = _keyed(lambda update: 1 / 0 if update.id == 2 else sequencing.chat_key(update))

    first = await _lane_of(dispatcher, make_message(5, message_id=1))

    assert first is not None
    assert await _lane_of(dispatcher, make_message(5, message_id=2)) is None
