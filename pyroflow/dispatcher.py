"""Patched Pyrogram dispatcher that routes updates through listeners, coordinators and histories."""

from __future__ import annotations as _annotations

import asyncio
import logging
from contextvars import ContextVar
from typing import Any, Final, TYPE_CHECKING

from pyrogram import StopPropagation, ContinuePropagation, raw
from pyrogram.dispatcher import Dispatcher as PyroDispatcher
from pyrogram.handlers import ErrorHandler, RawUpdateHandler, Handler as PyroHandler
from pytrove import maybe_awaitable, gather_helper, safe_await

from .errors import UnresolvedUpdate, UnhandledUpdate
from .utils import patch_cls

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable
    from concurrent.futures import Future

    from pyrogram.types import Update as PyroUpdate

    from .typings import UpdateType, AsyncLockProto, UpdateCoordinatorKeyT
    from .update_listener import UpdateListener
    from .update_coordinated import UpdateCoordinated
    from .update_history import UpdateHistory


log = logging.getLogger(__name__)

_HANDLED_MARKER: Final[ContextVar[_CoordinatedRelease | None]] = ContextVar(
    "pyroflow_handled_marker", default=None
)
"""Settlement of the update being processed, reachable from sync handlers in the executor and raw handlers too."""


class _CoordinatedRelease:
    """Settle one update's coordination exactly once.

    Settling registers the update as handled (when asked) and then releases its
    lock. `mark_handled` and `Dispatcher.handle_update` race for it; the first
    one wins and the other becomes a no-op.
    """

    __slots__ = ("_coordinated", "_lock", "_loop", "_early", "_released", "update_id")
    """Fixed attribute layout; a settlement is created per coordinated update."""

    def __init__(
        self,
        coordinated: UpdateCoordinated,
        lock: AsyncLockProto,
        loop: asyncio.AbstractEventLoop,
    ) -> None:
        """Bind the settlement to the update's coordinated, its held lock and the event loop.

        Args:
            coordinated: The coordinated whose coordinator registers the update as handled.
            lock: The already-acquired lock to release on settlement.
            loop: The event loop an early settlement is scheduled onto.
        """
        self._coordinated = coordinated
        """Coordinated whose coordinator registers the update as handled."""
        self._lock = lock
        """Held lock released on settlement."""
        self._loop = loop
        """Event loop an early settlement is scheduled onto."""
        self._early: Future[None] | asyncio.Future[None] | None = None
        """Scheduled early settlement, set once `mark_handled` claims it."""
        self._released: bool = False
        """Whether the settlement already ran."""

        self.update_id: UpdateCoordinatorKeyT | None = None
        """Update key, known only once the lock is held; a settlement before that registers nothing."""

    def claim_early(self) -> bool:
        """Claim the settlement and schedule it on the loop. Backs `mark_handled`.

        Safe to call from a thread outside the event loop, such as a sync
        handler in the client's executor.

        Returns:
            `True` if this call took the settlement, `False` if it was already
            claimed or settled.
        """
        if self._early is not None or self._released:
            return False

        coro, loop = self._settle(True), self._loop

        # Assigned here, not inside `coro`, so `settle` sees the claim at once.
        self._early = (
            asyncio.create_task(coro)
            if asyncio._get_running_loop() is loop
            else asyncio.run_coroutine_threadsafe(coro, loop)
        )

        return True

    async def settle(self, handled: bool) -> None:
        """Settle now, or wait out an early settlement if one won.

        Args:
            handled: Whether to register the update as handled; ignored when an
                early settlement already won.
        """
        if self._early is not None:
            # Don't abandon a settlement that is only scheduled: the dispatcher
            # may be stopped the moment the handler returns.
            await asyncio.wrap_future(self._early)
            return

        await self._settle(handled)

    async def _settle(self, handled: bool) -> None:
        """Register the update as handled if asked and known, then release the lock, once.

        Args:
            handled: Whether to register the update as handled.
        """
        if self._released:
            return

        self._released = True

        # `safe_await` logs backend errors instead of raising: the early
        # settlement runs detached, so nobody could catch them.

        try:
            if handled and self.update_id is not None:
                await safe_await(self._coordinated.coordinator.mark_handled(self.update_id))
        finally:
            await safe_await(self._lock.release())


@patch_cls(setter=setattr)
class Dispatcher(PyroDispatcher):
    """Pyrogram dispatcher extended with listeners, coordinators and histories.

    Patched onto `pyrogram.dispatcher.Dispatcher` in place, so every client uses
    it. Each update goes through `handle_update`: the coordinator (when one is
    registered for its type) runs everything under the update's lock and drops
    updates a peer already handled; then a registered listener gets the update
    first and, if it resolves it, propagation stops; then the first matching
    handler of each group runs, and the handlers that succeeded are recorded in
    the type's history when it is recordable.
    """

    old__init__: Callable[..., None]
    """Original Pyrogram initializer, kept by `patch_cls`."""
    oldstart: Callable[..., Awaitable[None]]
    """Original Pyrogram `start`, kept by `patch_cls`."""
    oldstop: Callable[..., Awaitable[None]]
    """Original Pyrogram `stop`, kept by `patch_cls`."""

    def __init__(self, *args: Any, **kw: Any) -> None:
        """Run the original initializer, then set up empty registries.

        Args:
            *args: Passed directly to the original dispatcher.
            **kw: Passed directly to the original dispatcher.
        """
        self.old__init__(*args, **kw)

        self.listeners: dict[type[PyroUpdate], UpdateListener[Any]] = {}
        """Registered listener per update type."""
        self.coordinateds: dict[type[PyroUpdate], UpdateCoordinated[Any]] = {}
        """Registered coordinated per update type."""
        self.histories: dict[type[PyroUpdate], UpdateHistory[Any]] = {}
        """Registered history per update type."""

        self.is_started = False
        """Whether the dispatcher is running; registration is refused while it is."""

    async def start(self, *args: Any, **kw: Any) -> None:
        """Start the dispatcher and all registered listeners, coordinators and histories.

        Args:
            *args: Passed directly to the original dispatcher.
            **kw: Passed directly to the original dispatcher.
        """
        r = await self.oldstart(*args, **kw)

        self.is_started = True

        await gather_helper(
            (listener.start() for listener in self.listeners.values()),
            (coordinated.start() for coordinated in self.coordinateds.values()),
            (history.start() for history in self.histories.values()),
            return_exc=True,
        )

        return r

    async def stop(self, *args: Any, **kw: Any) -> None:
        """Stop the dispatcher and all registered listeners, coordinators and histories.

        Args:
            *args: Passed directly to the original dispatcher.
            **kw: Passed directly to the original dispatcher.
        """
        await gather_helper(
            (listener.stop() for listener in self.listeners.values()),
            (coordinated.stop() for coordinated in self.coordinateds.values()),
            (history.stop() for history in self.histories.values()),
            return_exc=True,
        )

        r = await self.oldstop(*args, **kw)

        self.is_started = False

        return r

    def register_listener(self, listener: UpdateListener[UpdateType]) -> None:
        """Register a listener for its declared update type.

        Only one listener per update type, and only before the dispatcher starts.

        Args:
            listener: The listener to register.

        Raises:
            RuntimeError: If the dispatcher is already running.
            ValueError: If a listener is already registered for that update type.
        """
        if self.is_started:
            msg = "Cannot register listener while dispatcher is already running"
            raise RuntimeError(msg)

        update_type = listener.__class__.__update_type__

        if update_type in self.listeners:
            msg = f"UpdateListener for {update_type!r} is already registered"
            raise ValueError(msg)

        self.listeners[update_type] = listener

    def register_coordinated(self, coordinated: UpdateCoordinated[UpdateType]) -> None:
        """Register an `UpdateCoordinated` for its declared update type.

        Only one coordinated per update type, and only before the dispatcher starts.

        Args:
            coordinated: The coordinated to register.

        Raises:
            RuntimeError: If the dispatcher is already running.
            ValueError: If a coordinated is already registered for that update type.
        """
        if self.is_started:
            msg = "Cannot register coordinated while dispatcher is already running"
            raise RuntimeError(msg)

        update_type = coordinated.__class__.__update_type__

        if update_type in self.coordinateds:
            msg = f"UpdateCoordinated for {update_type!r} is already registered"
            raise ValueError(msg)

        self.coordinateds[update_type] = coordinated

    def register_history(self, history: UpdateHistory[UpdateType]) -> None:
        """Register an `UpdateHistory` for its declared update type.

        Only one history per update type, and only before the dispatcher starts.

        Args:
            history: The history to register.

        Raises:
            RuntimeError: If the dispatcher is already running.
            ValueError: If a history is already registered for that update type.
        """
        if self.is_started:
            msg = "Cannot register history while dispatcher is already running"
            raise RuntimeError(msg)

        update_type = history.__class__.__update_type__

        if update_type in self.histories:
            msg = f"UpdateHistory for {update_type!r} is already registered"
            raise ValueError(msg)

        self.histories[update_type] = history

    async def unregister_listener(self, update_type: type[PyroUpdate]) -> None:
        """Unregister and stop the listener for the given update type.

        Does nothing if no listener is registered for that type.

        Args:
            update_type: The Pyrogram update class whose listener to remove.
        """
        listener = self.listeners.pop(update_type, None)

        if listener is None:
            return

        await listener.stop()

    async def unregister_coordinated(self, update_type: type[PyroUpdate]) -> None:
        """Unregister and stop the coordinated for the given update type.

        Does nothing if no coordinated is registered for that type.

        Args:
            update_type: The Pyrogram update class whose coordinated to remove.
        """
        coordinated = self.coordinateds.pop(update_type, None)

        if coordinated is None:
            return

        await coordinated.stop()

    async def unregister_history(self, update_type: type[PyroUpdate]) -> None:
        """Unregister and stop the history for the given update type.

        Does nothing if no history is registered for that type.

        Args:
            update_type: The Pyrogram update class whose history to remove.
        """
        history = self.histories.pop(update_type, None)

        if history is None:
            return

        await history.stop()

    async def handle_listen(self, parsed_update: PyroUpdate) -> None:
        """Offer the update to the listener registered for its type.

        Listener errors are logged, not raised.

        Args:
            parsed_update: The parsed Pyrogram update to resolve.

        Raises:
            StopPropagation: If the listener resolved the update, so no handler
                runs.
        """
        listener = self.listeners.get(type(parsed_update))

        if listener is None:
            return

        try:
            await listener.resolve(parsed_update)
        except UnresolvedUpdate:
            pass
        except Exception:
            log.exception("Unexpected error in handle_listen")
        else:
            parsed_update.stop_propagation()

    async def _handle_update(
        self,
        packet: tuple[raw.base.Update, dict[int, raw.base.User], dict[int, raw.base.Chat]],
        parsed_update: PyroUpdate | None,
        handler_type: type[PyroHandler | None],
    ) -> tuple[int, int]:
        """Run the update through its listener, then the first matching handler of each group.

        Handlers that succeed are recorded in the update type's history when it
        is recordable. A handler error is passed to
        `handle_update_handler_exception` and does not stop the other groups.

        Args:
            packet: The raw `(update, users, chats)` tuple from Pyrogram.
            parsed_update: The parsed Pyrogram update, or `None`.
            handler_type: The handler class expected to handle this update.

        Returns:
            `(handled_count, exc_count)`: the handlers that succeeded and the
            handlers that raised.

        Raises:
            StopPropagation: If the listener resolved the update or a handler
                stopped propagation.
            UnhandledUpdate: If a handler raised it.
        """
        handled_count = exc_count = 0
        update, users, chats = packet

        if parsed_update is not None:
            await self.handle_listen(parsed_update)

        history = None

        if parsed_update is not None:
            history = self.histories.get(type(parsed_update))

        records = None

        if history is not None:
            try:
                if await history.is_recordable(parsed_update):
                    records = []
            except Exception:
                log.exception("Unexpected error checking is_recordable for %r", parsed_update)

        for group in self.groups.values():
            for handler in group:
                if isinstance(handler, ErrorHandler):
                    continue

                args = None

                if isinstance(handler, handler_type):
                    try:
                        if await handler.check(self.client, parsed_update):
                            args = (parsed_update,)
                    except Exception:
                        log.exception("Error in handler.check for handler %r", handler)
                        continue

                elif isinstance(handler, RawUpdateHandler):
                    try:
                        if await handler.check(self.client, update):
                            args = (update, users, chats)
                    except Exception:
                        log.exception("Error in raw handler.check for handler %r", handler)
                        continue

                if args is None:
                    continue

                try:
                    await maybe_awaitable(
                        handler.callback, self.client, *args, executor=self.client.executor
                    )
                except (StopPropagation, UnhandledUpdate) as e:
                    raise e
                except ContinuePropagation:
                    continue
                except Exception as exc:
                    exc_count += 1

                    await self.handle_update_handler_exception(exc, handler, update, users, chats)
                else:
                    handled_count += 1

                    if records is not None:
                        records.append(handler)

                break

        if history is not None and records:
            try:
                await history.record_many(parsed_update, records, check=False)
            except Exception:
                log.exception("Unexpected error recording handlers for %r", parsed_update)

        return handled_count, exc_count

    async def handle_update(
        self,
        packet: tuple[raw.base.Update, dict[int, raw.base.User], dict[int, raw.base.Chat]],
        parsed_update: PyroUpdate | None,
        handler_type: type[PyroHandler | None],
    ) -> None:
        """Process the update, under its coordinator when one applies.

        Without a coordinator for its type, or when the update is not
        coordinatable, the update is processed directly. Otherwise its lock is
        taken; an update a peer already handled is dropped, and any other is
        processed and then registered as handled if at least one handler ran,
        even one that raised. The lock is released once the update is settled,
        or earlier through `mark_handled`.

        If the lock times out the update is skipped and logged. If setting up
        coordination raises, the update is processed uncoordinated.

        Args:
            packet: The raw `(update, users, chats)` tuple from Pyrogram.
            parsed_update: The parsed Pyrogram update, or `None`.
            handler_type: The handler class expected to handle this update.

        Raises:
            StopPropagation: If the listener or a handler stopped propagation;
                a coordinated update is still registered as handled.
            UnhandledUpdate: If a handler raised it.
        """
        coordinated = self.coordinateds.get(type(parsed_update))

        if coordinated is None:
            await self._handle_update(packet, parsed_update, handler_type)
            return

        release = None

        try:
            if await coordinated.is_coordinatable(parsed_update):
                lock = await coordinated.lock(parsed_update)

                if not await lock.acquire():
                    log.error("Timeout waiting for coordinated lock on %r", parsed_update)
                    return

                # From here the lock is held, and only `release` gives it back.
                release = _CoordinatedRelease(coordinated, lock, self.client.loop)
        except Exception:
            log.exception("Error while acquiring coordinated lock")

        if release is None:
            await self._handle_update(packet, parsed_update, handler_type)
            return

        result = (0, 0)
        handled = False
        token = _HANDLED_MARKER.set(release)

        try:
            release.update_id = update_id = await coordinated.extract_update_id(parsed_update)

            if await coordinated.coordinator.is_handled(update_id):
                # A peer already handled and registered it.
                return

            result = await self._handle_update(packet, parsed_update, handler_type)
        except StopPropagation as e:
            handled = True
            raise e

        finally:
            _HANDLED_MARKER.reset(token)

            # `sum()` counts `exc_count` on purpose: a handler that raised still
            # ran, so replaying the update on a peer would duplicate work.
            if not handled:
                handled = sum(result) >= 1

            # A no-op if the handler already claimed the settlement through
            # `mark_handled()`. Always releases the lock.
            await release.settle(handled)

    async def handler_worker(self, lock: asyncio.Lock) -> None:
        """Parse and dispatch updates from the queue until a `None` sentinel arrives.

        Errors are logged, never raised, so the worker keeps running.

        Args:
            lock: The lock shared by all workers; each update is dispatched
                while holding it.
        """
        while True:
            packet = await self.updates_queue.get()

            if packet is None:
                break

            try:
                update, users, chats = packet
                parsed_update, handler_type = (
                    await parser(update, users, chats)  # ty: ignore[invalid-argument-type]  # `kurigram`'s `update_parsers` is an untyped dict of differently-typed parsers, so ty infers their union
                    if (parser := self.update_parsers.get(type(update))) is not None
                    else (None, type(None))
                )

                async with lock:
                    await self.handle_update(packet, parsed_update, handler_type)

            except (StopPropagation, UnhandledUpdate):
                pass
            except Exception:
                log.exception("Unexpected error in handler_worker")


def mark_handled() -> bool:
    """Register the current update as handled and release its lock now.

    Call it from a handler, sync or async, that keeps running after the work
    needing the lock is done. The settlement is scheduled on the event loop,
    not awaited. Later calls and the automatic settlement become no-ops. The
    lock's ordering ends here: the next update in its scope may start while
    this handler is still running.

    Returns:
        `True` if this call settled the update, `False` if the update is not
        coordinated, is already settled, or no update is being processed.

    Example:
        >>> mark_handled()  # outside update processing there is nothing to settle
        False
    """
    release = _HANDLED_MARKER.get()

    if release is None:
        return False

    return release.claim_early()


__all__ = (
    "Dispatcher",
    "mark_handled",
)
