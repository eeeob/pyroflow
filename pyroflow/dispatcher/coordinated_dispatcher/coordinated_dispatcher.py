"""The opt-in `CoordinatedDispatcher`: runs the updates that share a key one at a time."""

from __future__ import annotations as _annotations

import asyncio
import logging
from typing import Any, cast, TYPE_CHECKING

from pyrogram import StopPropagation
from pytrove import asafe_call

from ..dispatcher import _HANDLER_WORKER, _HANDLER_HOLD, Dispatcher
from .models import _HandlerHold, _Lane, _RawUpdate, _UpdateToParse, _UpdateToRun

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable

    from pyrogram.handlers import Handler as PyroHandler
    from pyrogram.types import Update as PyroUpdate

    from ...typings import CoordinationKeyT


log = logging.getLogger(__name__)
"""Logger for errors of parsers, key functions and coordinated handlers."""


class ZeroWaitCounter:
    """Counts the updates under way, and lets a task wait until none is left."""

    def __init__(self) -> None:
        """Initialise the counter at zero."""
        self._count = 0
        """How many updates are under way."""
        self._is_zero = asyncio.Event()
        """Set while no update is under way."""
        self._is_zero.set()

    def increment(self) -> None:
        """Count one more update."""
        self._count += 1
        self._is_zero.clear()

    def decrement(self) -> None:
        """Count one update less."""
        self._count -= 1

        if self._count == 0:
            self._is_zero.set()

    async def wait_until_zero(self) -> None:
        """Return once no update is under way."""
        await self._is_zero.wait()


class ArrivalOrder:
    """Keeps the order the updates were read in, whatever order they finish parsing in.

    Args:
        workers: How many updates may be read and not yet admitted.
    """

    def __init__(self, workers: int) -> None:
        """Initialise the order; see the class docstring for the parameters."""
        self.read_slots = asyncio.Semaphore(workers)
        """Taken to read an update and freed on its admission, so a slow parse holds back little."""
        self.all_admitted = asyncio.Event()
        """Set while every update numbered has been admitted."""
        self.all_admitted.set()
        self.numbers_given = 0
        """How many arrival numbers `give_next_number` gave."""
        self.next_number_to_admit = 0
        """The arrival number of the next update to admit."""
        self.parsed_ahead_of_turn: dict[int, _UpdateToRun | None] = {}
        """Updates that finished parsing ahead of their turn, by arrival number."""

    def give_next_number(self) -> int:
        """Return the arrival number of an update just taken from `updates_queue`."""
        self.numbers_given += 1
        self.all_admitted.clear()
        return self.numbers_given - 1

    def admit_in_order(
        self, arrival_number: int, update_to_run: _UpdateToRun | None
    ) -> list[_UpdateToRun]:
        """Take a parsed update, and return every update whose turn has come.

        Args:
            arrival_number: The update's number from `give_next_number`.
            update_to_run: The update; `None` if its parser failed.

        Returns:
            The updates to place now, oldest first.
        """
        self.parsed_ahead_of_turn[arrival_number] = update_to_run
        due_updates = []

        while self.next_number_to_admit in self.parsed_ahead_of_turn:
            next_update = self.parsed_ahead_of_turn.pop(self.next_number_to_admit)
            self.next_number_to_admit += 1
            self.read_slots.release()

            if next_update is not None:
                due_updates.append(next_update)

        if self.next_number_to_admit >= self.numbers_given:
            self.all_admitted.set()

        return due_updates

    async def wait_until_all_admitted(self) -> None:
        """Return once every update numbered has been admitted."""
        await self.all_admitted.wait()


class CoordinatedDispatcher(Dispatcher):
    """A `Dispatcher` that runs the updates that share a key one at a time.

    It stands alone, and starts with no handlers and no listeners. Install it
    right after creating the client, before anything is registered:
    `client.dispatcher = CoordinatedDispatcher(client, key_functions=[...])`.
    What was registered on the client's previous dispatcher is not carried
    over, and a client that has started keeps reading the dispatcher it
    started with.

    The `key_functions` extract the key of an update: the first to give a key
    decides, and `None` from one passes the update to the next. Updates of one
    key take turns in its lane, and keys of different functions never mix. An
    update no function gives a key runs free, and so does one with no parsed
    form. For a decision of your own, give a constant key, such as
    `lambda update: "payments" if is_payment(update) else None`.

    One task reads `updates_queue` and numbers each update, and the workers
    parse them side by side. Each parsed update is placed in its lane in the
    order read. The workers take what
    `worker_instructions` holds: they parse an update, or offer one to the
    listeners and then run its handlers. A handler holds its lane
    until it ends, its waits included. While it runs,
    one offer pass task shared by all the lanes offers the lane's
    `waiting_updates` to the waits, so no worker is needed for a reply.

    Everything lives in this process; nothing is shared between sessions.

    Warning:
        A wait with no timeout freezes its key for good, along with any
        `/cancel` handler of the key, which is just another queued update.
        Bound the waits of coordinated handlers with a timeout.

        The workers parse the replies too: when every worker waits, no reply
        is parsed until a wait ends. Set a `workers_policy` with
        `Client.setup_pyroflow`, which keeps one worker out of the waits, and
        bound with a timeout the waits it does not count, as in
        `asyncio.gather` or in a sync handler.

    Args:
        *args: Passed to `Dispatcher`: the client whose dispatcher this replaces.
        key_functions: `(update) -> key`, sync, as updates are placed in order.
        **kw: Passed to `Dispatcher`.

    Example:
        >>> def chat_key(update):
        ...     return update.chat.id
        >>> import pyroflow
        >>> client = pyroflow.Client("doc", api_id=1, api_hash="x", in_memory=True)
        >>> dispatcher = CoordinatedDispatcher(client, key_functions=[chat_key])
        >>> dispatcher.key_functions == (chat_key,)
        True
    """

    def __init__(
        self,
        *args: object,
        key_functions: Iterable[Callable[[PyroUpdate], CoordinationKeyT | None]] = (),
        **kw: object,
    ) -> None:
        """Initialise the dispatcher; see the class docstring for the parameters."""
        super().__init__(*args, **kw)

        self.key_functions = tuple(key_functions)
        """The key functions, in order."""
        self.lanes_by_key: dict[CoordinationKeyT, _Lane] = {}
        """The keys with work, each as `(index of its function, key)`."""
        self.worker_instructions: asyncio.Queue[_UpdateToParse | _UpdateToRun | None] = (
            asyncio.Queue()
        )
        """The instructions for the workers: an update to parse or to run, or `None` to stop."""
        self.arrival_order = ArrivalOrder(self.client.workers)
        """The order the updates of the current run were read in."""
        self.offer_pass_requests: asyncio.Queue[_HandlerHold | None] = asyncio.Queue()
        """The holds whose `waiting_updates` are to be offered to their waits, or `None` to end."""
        self.wait_generation = 0
        """Moves with each wait a coordinated handler starts."""
        self.reader_task: asyncio.Task[None] | None = None
        """The task that reads `updates_queue`, while running."""
        self.offer_pass_task: asyncio.Task[None] | None = None
        """The one task that offers queued updates to the waits, while running."""
        self.unfinished_updates: ZeroWaitCounter = ZeroWaitCounter()
        """The updates placed in the current run and not over yet."""

    async def handle_listen(self, parsed_update: PyroUpdate) -> bool:
        """Offer the update to its listener, and count it as over if the listener takes it.

        Args:
            parsed_update: The parsed update.

        Returns:
            Whether the listener took the update.
        """
        if await super().handle_listen(parsed_update):
            self.unfinished_updates.decrement()
            return True
        return False

    async def handle_update(
        self,
        packet: _RawUpdate,
        parsed_update: PyroUpdate | None,
        handler_type: type[PyroHandler | None],
    ) -> None:
        """Run the handlers of the update, and count it as over once they end.

        Args:
            packet: The update, raw.
            parsed_update: The parsed update, or `None`.
            handler_type: The handler class the parser gave the update.

        Raises:
            StopPropagation: If a handler stopped propagation.
        """
        try:
            await super().handle_update(packet, parsed_update, handler_type)
        finally:
            self.unfinished_updates.decrement()

    async def start(self, *args: object, **kw: object) -> None:
        """Start as usual, then start reading.

        The updates the original `start` recovers wait in `updates_queue` for
        the reader.

        Args:
            *args: Passed to `Dispatcher.start`.
            **kw: Passed to `Dispatcher.start`.
        """
        reads_updates = not self.client.no_updates
        workers = self.client.workers

        if reads_updates:
            # A new run forgets what the last one left.
            self.worker_instructions = asyncio.Queue()
            self.arrival_order = ArrivalOrder(workers)
            self.offer_pass_requests = asyncio.Queue()
            self.wait_generation = 0
            self.lanes_by_key.clear()
            self.unfinished_updates = ZeroWaitCounter()

        await super().start(*args, **kw)

        if reads_updates:
            self.reader_task = asyncio.create_task(self._read_updates(workers))
            self.offer_pass_task = asyncio.create_task(self._run_offer_passes())

    async def stop(self, *args: object, **kw: object) -> None:
        """Stop as usual, then wait for the reader and the offers, so `start` can follow at once.

        Args:
            *args: Passed to `Dispatcher.stop`.
            **kw: Passed to `Dispatcher.stop`.
        """
        await super().stop(*args, **kw)

        for task in (self.reader_task, self.offer_pass_task):
            if task is None:
                continue
            await asafe_call(task, include_exc=asyncio.CancelledError)

        self.reader_task = self.offer_pass_task = None

    async def handler_worker(self) -> None:
        """Carry out what `worker_instructions` holds until it tells this worker to stop."""
        # Always called from a task.
        worker_token = _HANDLER_WORKER.set(cast("asyncio.Task[None]", asyncio.current_task()))
        # A client started inside a handler must not take that handler's hold for its own.
        outer_hold_token = _HANDLER_HOLD.set(None)

        try:
            while True:
                instruction = await self.worker_instructions.get()

                if instruction is None:
                    break

                if isinstance(instruction, _UpdateToParse):
                    await self._parse_and_place(instruction)
                    continue

                handler_hold_token = None

                try:
                    if instruction.parsed_update is not None and await self.handle_listen(
                        instruction.parsed_update
                    ):
                        continue

                    lane = instruction.lane

                    # An update that runs free keeps the worker's `None`.
                    if lane is not None:
                        lane.handler_hold = _HandlerHold(lane, self.wait_generation)
                        handler_hold_token = _HANDLER_HOLD.set(lane.handler_hold)
                        lane.handler_hold.request_offer_pass(self.offer_pass_requests)

                    await self.handle_update(
                        instruction.raw_update,
                        instruction.parsed_update,
                        instruction.handler_type,
                    )
                except StopPropagation:
                    pass
                except Exception:
                    log.exception("Unexpected error in handler_worker")
                finally:
                    if handler_hold_token is not None:
                        _HANDLER_HOLD.reset(handler_hold_token)

                    lane = instruction.lane

                    if lane is not None:
                        if lane.handler_hold is not None:
                            # Nothing below suspends, so the lane moves on between two offers.
                            await lane.handler_hold.wait_offer_lock()

                            lane.handler_hold = None

                        if lane.waiting_updates:
                            self.worker_instructions.put_nowait(lane.waiting_updates.popleft())
                        else:
                            # Idle: the next update of its key opens a new lane.
                            self.lanes_by_key.pop(lane.key)
        finally:
            _HANDLER_HOLD.reset(outer_hold_token)
            _HANDLER_WORKER.reset(worker_token)

    async def _read_updates(self, workers: int) -> None:
        """Read `updates_queue` alone, number each update, and queue it for a worker to parse.

        Parsing in the workers, not here, lets a parse that waits on the
        network hold back no other parse, and `ArrivalOrder` still places the
        updates in the order read. At most `workers` updates are read and not
        yet placed, so the parses queued stay few.

        Reads the stop sentinels of `Dispatcher.stop`, waits for the updates
        read to be over, and then stops the workers and the offer task.

        Args:
            workers: How many workers the run has, and so how many sentinels end the reading.
        """
        arrival_order = self.arrival_order
        stop_signals_read = 0

        while stop_signals_read < workers:
            await arrival_order.read_slots.acquire()
            raw_update = await self.updates_queue.get()

            if raw_update is None:
                arrival_order.read_slots.release()
                stop_signals_read += 1
                continue

            self.worker_instructions.put_nowait(
                _UpdateToParse(arrival_order.give_next_number(), raw_update)
            )

        # A lane posts its next update as the last one ends, so the workers stop after them all.
        await arrival_order.wait_until_all_admitted()
        await self.unfinished_updates.wait_until_zero()

        for _ in range(stop_signals_read):
            self.worker_instructions.put_nowait(None)

        self.offer_pass_requests.put_nowait(None)

    async def _parse_and_place(self, update_to_parse: _UpdateToParse) -> None:
        """Parse an update, then place in their lanes, in the order read, the updates whose turn came.

        An update that fails to parse is dropped. The first key function to
        give a key names the lane; a key function that fails, or gives a value
        that is not hashable, is logged, and the update goes to the next
        function.

        Args:
            update_to_parse: The update, raw, with its arrival number.
        """
        parsed = None

        try:
            update, users, chats = cast("Any", update_to_parse.raw_update)
            parsed_update, handler_type = (
                await parser(update, users, chats)
                if (parser := self.update_parsers.get(type(update))) is not None
                else (None, type(None))
            )
            parsed = _UpdateToRun(update_to_parse.raw_update, parsed_update, handler_type)
        except Exception:
            log.exception("Error parsing an update; it is dropped")
        finally:
            # Even a cancelled parse fills its turn, or nothing behind it would ever be placed.
            for update_to_run in self.arrival_order.admit_in_order(
                update_to_parse.arrival_number, parsed
            ):
                parsed_update = update_to_run.parsed_update
                lane = None

                if parsed_update is not None:
                    for index, function in enumerate(self.key_functions):
                        try:
                            key = function(parsed_update)

                            # `None` passes the update to the next key function.
                            if key is None:
                                continue

                            function_and_key = (index, key)

                            if function_and_key not in self.lanes_by_key:
                                self.lanes_by_key[function_and_key] = _Lane(function_and_key)
                        except Exception:
                            log.exception(
                                "Error in a key function; the update goes to the next one"
                            )
                            continue

                        lane = self.lanes_by_key[function_and_key]

                        break

                # Placed in the order read, so no update overtakes an earlier one of its key.
                update_to_run.lane = lane
                self.unfinished_updates.increment()

                if lane is None:
                    self.worker_instructions.put_nowait(update_to_run)
                elif not lane.turn_taken:
                    lane.turn_taken = True
                    self.worker_instructions.put_nowait(update_to_run)
                else:
                    lane.waiting_updates.append(update_to_run)

                    if lane.handler_hold is not None:
                        lane.handler_hold.request_offer_pass(self.offer_pass_requests)

    async def _run_offer_passes(self) -> None:
        """Run the offer passes in `offer_pass_requests`, outside any lock.

        Each offer pass offers the `waiting_updates` of a lane to the waits, in
        order: each update once since the handler's last wait started. What a
        wait of the handler declined is still offered, for the other waits.

        Each offer holds `offer_lock`, so a wait starts, and the handler ends,
        only between two offers; the pass reads where it is again after each.

        Runs in its own task, not in a task that waits, so a wait reaches its
        future at once, and a filter that waits delays only other offers.
        """
        _HANDLER_HOLD.set(None)

        while True:
            hold = await self.offer_pass_requests.get()

            if hold is None:
                break

            waiting_updates = hold.lane.waiting_updates

            try:
                while True:
                    async with hold.offer_lock:
                        if hold.handler_ended() or hold.offer_pass_position >= len(waiting_updates):
                            break

                        update_to_run = waiting_updates[hold.offer_pass_position]

                        if update_to_run.offered_at_generation >= hold.last_wait_generation:
                            hold.offer_pass_position += 1
                            continue

                        update_to_run.offered_at_generation = hold.last_wait_generation

                        # Only updates with a parsed form queue.
                        if await self.handle_listen(
                            cast("PyroUpdate", update_to_run.parsed_update)
                        ):
                            waiting_updates.remove(update_to_run)
            finally:
                hold.offer_pass_active = False


__all__ = ("CoordinatedDispatcher",)
