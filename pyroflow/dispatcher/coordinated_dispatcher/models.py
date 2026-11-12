"""The data of the coordination: the updates, their lanes, and the holds on them."""

from __future__ import annotations as _annotations

import asyncio
import weakref

from collections import deque
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, TypeAlias

from pyrogram import raw
from pyrogram.handlers import Handler as PyroHandler
from pyrogram.types import Update as PyroUpdate

from ...typings import CoordinationKeyT

if TYPE_CHECKING:
    from ...models import ListenerModel
    from .coordinated_dispatcher import CoordinatedDispatcher

_RawUpdate: TypeAlias = tuple[raw.base.Update, dict[int, raw.base.User], dict[int, raw.base.Chat]]
"""The raw `(update, users, chats)` tuple from `updates_queue`."""


@dataclass(eq=False, slots=True)
class _UpdateToParse:
    """An update read and not yet parsed; the instruction to parse it."""

    arrival_number: int
    """Its place in the order read, from `ArrivalOrder.give_next_number`."""
    raw_update: _RawUpdate
    """The update, raw."""


@dataclass(eq=False, slots=True)
class _UpdateToRun:
    """An update on its way through the dispatcher, parsed; the instruction to run it."""

    raw_update: _RawUpdate
    """The update, raw."""
    parsed_update: PyroUpdate | None
    """The parsed update; `None` if no parser gives one, for raw handlers alone."""
    handler_type: type[PyroHandler | None]
    """The handler class the parser gave the update."""
    lane: _Lane | None = None
    """The lane the update takes its turn in; `None` if it runs free."""
    offered_at_generation: int = -1
    """The hold's `last_wait_generation` when the update was last offered; `-1` if never."""


@dataclass(eq=False, slots=True)
class _HandlerHold:
    """The claim of one running handler on its lane, until the handler ends.

    `CoordinatedDispatcher` opens it and names it the lane's `handler_hold`
    while the handler runs, and runs its offer passes; `UpdateListener.listen`
    notes the waits of the handler through `note_handler_wait`.
    """

    lane: _Lane
    """The lane."""
    last_wait_generation: int
    """The dispatcher's `wait_generation` when this handler last started a wait, or when it started."""
    offer_pass_active: bool = False
    """Whether an offer pass of this hold is requested or under way."""
    offer_pass_position: int = 0
    """Where the offer pass is in `waiting_updates`; what is before it was offered already."""
    offer_lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    """Held through each offer, so a wait starts, and the handler ends, only between two offers."""
    declined_by_handler_waits: weakref.WeakValueDictionary[int, PyroUpdate] = field(
        default_factory=weakref.WeakValueDictionary
    )
    """What the waits of this handler declined, by `id`, for its later waits to skip; weak."""

    def handler_ended(self) -> bool:
        """Whether the handler ended: the lane no longer names this hold; its later waits do not count."""
        return self.lane.handler_hold is not self

    def request_offer_pass(self, offer_pass_requests: asyncio.Queue[_HandlerHold | None]) -> None:
        """Queue an offer pass of this hold, if its lane has updates waiting and no pass is queued or under way.

        Args:
            offer_pass_requests: The queue of the offer passes to run.
        """
        if self.lane.waiting_updates and not self.offer_pass_active:
            self.offer_pass_active = True
            offer_pass_requests.put_nowait(self)

    def note_handler_wait(self, dispatcher: CoordinatedDispatcher, listener: ListenerModel) -> None:
        """Note a wait of this handler, and have `waiting_updates` offered from the head.

        Called by `UpdateListener.listen` once the wait is registered, between
        two offers of the lane, never during one. A wait that starts once the
        handler ended counts for nothing here.

        Args:
            dispatcher: The dispatcher running the handler.
            listener: The wait.
        """
        if self.handler_ended():
            return

        listener.on_declined_update = self.on_handler_wait_declined
        # What the earlier waits of the handler declined is no reply to this one either.
        listener.declined_updates.update(self.declined_by_handler_waits)
        dispatcher.wait_generation += 1
        self.last_wait_generation = dispatcher.wait_generation
        self.offer_pass_position = 0
        self.request_offer_pass(dispatcher.offer_pass_requests)

    def on_handler_wait_declined(self, update: PyroUpdate) -> None:
        """Keep `update` from the later waits of this handler; their `on_declined_update`.

        A declined update is not a reply, as with a plain `Dispatcher`: it runs
        its handlers in its turn. And a handler that asks again with `strict`
        is not refused the same queued update forever.

        Args:
            update: The update declined.
        """
        self.declined_by_handler_waits[id(update)] = update

    async def wait_offer_lock(self, handler_active_required: bool = False) -> bool:
        """Wait until no offer of this hold is under way, so what follows runs between two offers.

        Args:
            handler_active_required: Return at once, without waiting, if the handler ended.

        Returns:
            Whether it waited; `False` only with `handler_active_required` and the handler ended.
        """
        if handler_active_required and self.handler_ended():
            return False

        async with self.offer_lock:
            return True


@dataclass(eq=False, slots=True)
class _Lane:
    """Updates of one key that take turns: one runs or is posted, and the rest wait here."""

    key: CoordinationKeyT
    """The lane's key in `lanes_by_key`: `(index of its function, key)`."""
    waiting_updates: deque[_UpdateToRun] = field(default_factory=deque)
    """The updates behind the one running, oldest first."""
    handler_hold: _HandlerHold | None = None
    """The hold of the running handler; `None` while no handler runs."""
    turn_taken: bool = False
    """Whether an update of the lane is running or posted."""


__all__ = ()
