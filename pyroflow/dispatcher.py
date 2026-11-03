"""Patched Pyrogram dispatcher that routes updates through listeners and coordinators."""

from __future__ import annotations as _annotations

import logging
from contextvars import ContextVar
from typing import Any, Final, TYPE_CHECKING

from pyrogram import StopPropagation, ContinuePropagation, raw
from pyrogram.dispatcher import Dispatcher as PyroDispatcher
from pyrogram.handlers import ErrorHandler, RawUpdateHandler, Handler as PyroHandler
from pytrove import maybe_awaitable, gather_helper, safe_await

from .errors import UnresolvedUpdate, UpdateAlreadyHandled
from .utils import patch_cls

if TYPE_CHECKING:
    import asyncio
    from collections.abc import Awaitable, Callable

    from pyrogram.types import Update as PyroUpdate

    from .typings import UpdateType, AsyncLockProto, CoordinatedUpdateIdT
    from .update_listener import UpdateListener
    from .update_coordinated import UpdateCoordinated
    from .update_coordinator import UpdateCoordinator


log = logging.getLogger(__name__)

_SETTLEMENT: Final[ContextVar[_CoordinatedRelease | None]] = ContextVar(
    "pyroflow_settlement", default=None
)
"""Settlement of the coordinated update being processed, or `None` when it is not coordinated."""


class _CoordinatedRelease:
    """Settle one coordinated update once: mark it as handled if asked, then release its lock."""

    __slots__ = ("_coordinator", "_lock", "_settled", "_update_id")
    """Fixed attribute layout; a settlement is created per coordinated update."""

    def __init__(
        self,
        coordinator: UpdateCoordinator,
        lock: AsyncLockProto,
        update_id: CoordinatedUpdateIdT,
    ) -> None:
        """Bind the settlement to the update's coordinator, its held lock and its identity.

        Args:
            coordinator: The coordinator that marks the update as handled.
            lock: The already-acquired lock to release on settlement.
            update_id: The identity marked as handled.
        """
        self._coordinator = coordinator
        """Coordinator that marks the update as handled."""
        self._lock = lock
        """Held lock released on settlement."""
        self._update_id = update_id
        """Identity marked as handled."""
        self._settled: bool = False
        """Whether the settlement already ran."""

    async def settle(self, handled: bool) -> bool:
        """Mark the update as handled if `handled`, then release the lock; later calls do nothing.

        Backend errors are logged, not raised, so the lock is always released.

        Args:
            handled: Whether to mark the update as handled.

        Returns:
            `False` if a peer had already marked the update, so this session
            must drop it; `True` otherwise, including on later calls.
        """
        if self._settled:
            return True

        self._settled = True

        try:
            if handled:
                await self._coordinator.mark_handled(self._update_id)
        except UpdateAlreadyHandled:
            log.warning("Update %r was already handled by a peer; dropping it", self._update_id)
            return False
        except Exception:
            log.exception("Error marking update %r as handled", self._update_id)
        finally:
            await safe_await(self._lock.release())

        return True


async def _settle_handled() -> bool:
    """Mark the update being processed as handled and release its lock, if it is coordinated.

    Returns:
        `False` if a peer had already marked the update, so it must be
        dropped; `True` otherwise, including when it is not coordinated.
    """
    release = _SETTLEMENT.get()

    if release is None:
        return True

    return await release.settle(True)


@patch_cls(setter=setattr)
class Dispatcher(PyroDispatcher):
    """Pyrogram dispatcher extended with listeners and coordinators.

    Patched onto `pyrogram.dispatcher.Dispatcher` in place, so every client uses
    it. Each update goes through `handle_update`: the coordinator (when one is
    registered for its type) takes the update's lock, drops updates a peer
    already handled, and marks the update as handled and releases the lock as
    soon as a listener resolves it or a handler's filter passes it; then a
    registered listener gets the update
    first and, if it resolves it, propagation stops; then the first matching
    handler of each group runs.
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

        self.is_started = False
        """Whether the dispatcher is running; registration is refused while it is."""

    async def start(self, *args: Any, **kw: Any) -> None:
        """Start the dispatcher and all registered listeners and coordinators.

        Args:
            *args: Passed directly to the original dispatcher.
            **kw: Passed directly to the original dispatcher.
        """
        r = await self.oldstart(*args, **kw)

        self.is_started = True

        await gather_helper(
            (listener.start() for listener in self.listeners.values()),
            (coordinated.start() for coordinated in self.coordinateds.values()),
            return_exc=True,
        )

        return r

    async def stop(self, *args: Any, **kw: Any) -> None:
        """Stop the dispatcher and all registered listeners and coordinators.

        Args:
            *args: Passed directly to the original dispatcher.
            **kw: Passed directly to the original dispatcher.
        """
        await gather_helper(
            (listener.stop() for listener in self.listeners.values()),
            (coordinated.stop() for coordinated in self.coordinateds.values()),
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

    async def handle_listen(self, parsed_update: PyroUpdate) -> None:
        """Offer the update to the listener registered for its type.

        Listener errors are logged, not raised.

        Args:
            parsed_update: The parsed Pyrogram update to resolve.

        A resolved coordinated update is marked as handled and its lock
        released before propagation stops.

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
            await _settle_handled()
            parsed_update.stop_propagation()

    async def _handle_update(
        self,
        packet: tuple[raw.base.Update, dict[int, raw.base.User], dict[int, raw.base.Chat]],
        parsed_update: PyroUpdate | None,
        handler_type: type[PyroHandler | None],
    ) -> tuple[int, int]:
        """Run the update through its listener, then the first matching handler of each group.

        A handler error is passed to `handle_update_handler_exception` and does
        not stop the other groups.
        A coordinated update a peer marked first is dropped before any handler
        runs.

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
        """
        handled_count = exc_count = 0
        update, users, chats = packet

        if parsed_update is not None:
            await self.handle_listen(parsed_update)

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

                # A passing filter makes a coordinated update handled; the
                # handler then runs without its lock.
                if not await _settle_handled():
                    # A peer handled it while this session held the lock.
                    return handled_count, exc_count

                try:
                    await maybe_awaitable(
                        handler.callback,
                        self.client,
                        *args,
                        executor=self.client.executor,
                        log_exc=False,
                    )
                except StopPropagation as e:
                    raise e
                except ContinuePropagation:
                    continue
                except Exception as exc:
                    exc_count += 1

                    await self.handle_update_handler_exception(exc, handler, update, users, chats)
                else:
                    handled_count += 1

                break

        return handled_count, exc_count

    async def handle_update(
        self,
        packet: tuple[raw.base.Update, dict[int, raw.base.User], dict[int, raw.base.Chat]],
        parsed_update: PyroUpdate | None,
        handler_type: type[PyroHandler | None],
    ) -> None:
        """Process the update, under its coordinator when one applies.

        Without a coordinator for its type, or when its key is `None`, the
        update is processed directly. Otherwise the key's lock is taken and an
        update a peer already handled is dropped. Any other is processed; the
        first listener that resolves it or handler filter that passes it marks
        it as handled and releases the lock, and the handlers run on without
        it. An update nothing took is released unmarked, so a peer may take it.

        If the lock times out the update is skipped and logged. If setting up
        coordination raises, the error is logged and the update is processed
        uncoordinated.

        Args:
            packet: The raw `(update, users, chats)` tuple from Pyrogram.
            parsed_update: The parsed Pyrogram update, or `None`.
            handler_type: The handler class expected to handle this update.

        Raises:
            StopPropagation: If the listener or a handler stopped propagation.
        """
        coordinated = self.coordinateds.get(type(parsed_update))

        if coordinated is None:
            await self._handle_update(packet, parsed_update, handler_type)
            return

        release = None

        try:
            key = await coordinated.extract_key(parsed_update)

            if key is not None:
                lock = coordinated.coordinator.lock(key)

                if not await lock.acquire():
                    log.error("Timeout waiting for coordinated lock on %r", parsed_update)
                    return

                try:
                    update_id = await coordinated.extract_update_id(parsed_update)
                    handled = await coordinated.coordinator.is_handled(update_id)
                except BaseException:
                    await safe_await(lock.release())
                    raise

                if handled:
                    # A peer already handled it.
                    await safe_await(lock.release())
                    return

                release = _CoordinatedRelease(coordinated.coordinator, lock, update_id)
        except Exception:
            log.exception("Error while setting up coordination for %r", parsed_update)

        if release is None:
            await self._handle_update(packet, parsed_update, handler_type)
            return

        token = _SETTLEMENT.set(release)

        try:
            await self._handle_update(packet, parsed_update, handler_type)
        finally:
            _SETTLEMENT.reset(token)

            # A no-op once a listener or a passing filter settled it as handled.
            await release.settle(False)

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

            except StopPropagation:
                pass
            except Exception:
                log.exception("Unexpected error in handler_worker")


__all__ = ("Dispatcher",)
