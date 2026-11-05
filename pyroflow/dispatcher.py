"""Patched Pyrogram dispatcher that offers each update to its listener before the handlers."""

from __future__ import annotations as _annotations

import logging
from typing import Any, TYPE_CHECKING

from pyrogram import StopPropagation, ContinuePropagation, raw
from pyrogram.dispatcher import Dispatcher as PyroDispatcher
from pyrogram.handlers import ErrorHandler, RawUpdateHandler, Handler as PyroHandler
from pytrove import maybe_awaitable, gather_helper

from .utils import patch_cls

if TYPE_CHECKING:
    import asyncio
    from collections.abc import Awaitable, Callable

    from pyrogram.types import Update as PyroUpdate

    from .typings import UpdateType
    from .update_listener import UpdateListener


log = logging.getLogger(__name__)


@patch_cls(setter=setattr)
class Dispatcher(PyroDispatcher):
    """Pyrogram dispatcher extended with listeners.

    Patched onto `pyrogram.dispatcher.Dispatcher` in place, so every client uses
    it. Each update goes through `handle_update`: the listener registered for
    its type gets it first and, if it takes it, propagation stops; otherwise
    the first matching handler of each group runs.
    """

    old__init__: Callable[..., None]
    """Original Pyrogram initializer, kept by `patch_cls`."""
    oldstart: Callable[..., Awaitable[None]]
    """Original Pyrogram `start`, kept by `patch_cls`."""
    oldstop: Callable[..., Awaitable[None]]
    """Original Pyrogram `stop`, kept by `patch_cls`."""

    def __init__(self, *args: object, **kw: object) -> None:
        """Run the original initializer, then set up an empty listener registry.

        Args:
            *args: Passed directly to the original dispatcher.
            **kw: Passed directly to the original dispatcher.
        """
        self.old__init__(*args, **kw)

        self.listeners: dict[type[PyroUpdate], UpdateListener[Any]] = {}
        """Registered listener per update type."""

        self.is_started = False
        """Whether the dispatcher is running; registration is refused while it is."""

    async def start(self, *args: object, **kw: object) -> None:
        """Start all registered listeners, then the dispatcher.

        The listeners go first: the original `start` already dispatches the
        updates missed while stopped, and a handler among them may `listen`.

        Args:
            *args: Passed directly to the original dispatcher.
            **kw: Passed directly to the original dispatcher.
        """
        await gather_helper(
            (listener.start() for listener in self.listeners.values()),
            return_exc=True,
        )

        r = await self.oldstart(*args, **kw)

        self.is_started = True

        return r

    async def stop(self, *args: object, **kw: object) -> None:
        """Stop the listeners, then the original dispatcher.

        The listeners go first: their waiters fail, so a handler blocked in
        `ask` returns and the original `stop` can drain the workers.

        Args:
            *args: Passed directly to the original dispatcher.
            **kw: Passed directly to the original dispatcher.
        """
        await gather_helper(
            (listener.stop() for listener in self.listeners.values()),
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

    async def unregister_listener(self, update_type: type[PyroUpdate]) -> None:
        """Unregister and stop the listener for the given update type.

        Does nothing if no listener is registered for that type.

        Args:
            update_type: The Pyrogram update class whose listener to remove.
        """
        listener = self.listeners.pop(update_type, None)

        if listener is not None:
            await listener.stop()

    async def handle_listen(self, parsed_update: PyroUpdate) -> None:
        """Offer the update to the listener registered for its type.

        A listener error is logged and the update goes on to the handlers.

        Args:
            parsed_update: The parsed Pyrogram update to resolve.

        Raises:
            StopPropagation: If the listener took the update; no handler runs.
        """
        listener = self.listeners.get(type(parsed_update))

        if listener is None:
            return

        try:
            resolved = await listener.resolve(parsed_update)
        except Exception:
            log.exception("Unexpected error in handle_listen")
            return

        if resolved:
            parsed_update.stop_propagation()

    async def handle_update(
        self,
        packet: tuple[raw.base.Update, dict[int, raw.base.User], dict[int, raw.base.Chat]],
        parsed_update: PyroUpdate | None,
        handler_type: type[PyroHandler | None],
    ) -> None:
        """Run the update through its listener, then the first matching handler of each group.

        A handler error is passed to `handle_update_handler_exception` and does
        not stop the other groups.

        Args:
            packet: The raw `(update, users, chats)` tuple from Pyrogram.
            parsed_update: The parsed Pyrogram update, or `None`.
            handler_type: The handler class expected to handle this update.

        Raises:
            StopPropagation: If the listener took the update or a handler
                stopped propagation.
        """
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
                    await self.handle_update_handler_exception(exc, handler, update, users, chats)

                break

    async def handler_worker(self, lock: asyncio.Lock) -> None:
        """Parse and dispatch updates from the queue until a `None` sentinel arrives.

        Errors are logged, never raised, so the worker keeps running.

        Args:
            lock: This worker's own lock; each update is dispatched while
                holding it.
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
