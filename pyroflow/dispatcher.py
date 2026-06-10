from typing import Dict, Tuple, Type, Optional, Callable

from pyrogram import (
    StopPropagation, 
    ContinuePropagation, 
    raw
)
from pyrogram.dispatcher import Dispatcher as PyroDispatcher
from pyrogram.handlers import ErrorHandler, RawUpdateHandler, Handler as PyroHandler
from pyrogram.types import Update as PyroUpdate

from .utils.typings import UpdateType
from .utils import maybe_awaitable, gather_helper, patch_cls

from .errors import UnresolvedUpdate
from .enums import UpdateLockState
from .update_listener import UpdateListener
from .update_coordinated import UpdateCoordinated
from .update_history import UpdateHistory

import logging


log = logging.getLogger(__name__)


@patch_cls(setter=setattr)
class Dispatcher(PyroDispatcher):
    """
    Extended Pyrogram dispatcher that layers three systems on top of
    the standard handler pipeline: listeners, coordinators, and histories.

    Applied via ``@patch_cls``, which monkey-patches
    :class:`pyrogram.dispatcher.Dispatcher` in-place so that every
    :class:`pyrogram.Client` instance uses this implementation without
    requiring any subclassing on the user's side.

    Update flow
    -----------
    For every incoming update the pipeline runs in this order:

    1. **Listener** (:meth:`handle_listen`) — if a :class:`UpdateListener`
       is registered for the update type, it is given first priority.
       A successful resolve calls ``stop_propagation()`` and skips steps
       2–3 entirely.

    2. **Coordinator** (:meth:`handle_update`) — if a
       :class:`UpdateCoordinated` is registered, a distributed lock is
       acquired before processing. This guarantees that the same update
       is handled by exactly one session across multiple servers.
       The lock is released with :attr:`UpdateLockState.HANDLED` only
       if at least one handler executed without raising an exception;
       otherwise it is released with ``None`` so another session can
       retry.

    3. **Handler groups** (:meth:`_handle_update`) — iterates Pyrogram's
       normal handler groups. The first matching handler per group is
       invoked. Successful invocations are optionally recorded by a
       :class:`UpdateHistory` (see below).

    4. **History** — if a :class:`UpdateHistory` is registered and
       :meth:`UpdateHistory.is_recordable` returns ``True``, every
       handler that ran successfully in step 3 is appended to the
       history record via :meth:`UpdateHistory.record_many`. This allows
       later handlers (e.g. a ``back`` button) to inspect or replay
       previous processing steps.

    Attributes:
        listeners:    Mapping from update type to its :class:`UpdateListener`.
        coordinateds: Mapping from update type to its :class:`UpdateCoordinated`.
        histories:    Mapping from update type to its :class:`UpdateHistory`.
        is_started:   ``True`` while the dispatcher is running.
    """

    old__init__: Callable
    oldstart: Callable
    oldstop: Callable

    def __init__(self, *args, **kw) -> None:
        self.old__init__(*args, **kw)

        self.listeners: Dict[Type[UpdateType], UpdateListener[UpdateType]] = {}
        self.coordinateds: Dict[Type[UpdateType], UpdateCoordinated[UpdateType]] = {}
        self.histories: Dict[Type[UpdateType], UpdateHistory[UpdateType]] = {}

        self.is_started = False
    

    async def start(self, *args, **kw) -> None:
        """
        Start the dispatcher and all registered listeners, coordinators and histories.

        Parameters:
            *args: Passed directly to the original dispatcher.
            **kw: Passed directly to the original dispatcher.
        """

        await self.oldstart(*args, **kw)

        self.is_started = True

        await gather_helper(
            (listener.start()
            for listener in self.listeners.values()), 
            (coordinated.start()
            for coordinated in self.coordinateds.values()), 
            (history.start()
            for history in self.histories.values()), 
            return_exc=True
        )

    async def stop(self, *args, **kw) -> None:
        """
        Stop the dispatcher and all registered listeners, coordinators and histories.

        Parameters:
            *args: Passed directly to the original dispatcher.
            **kw: Passed directly to the original dispatcher.
        """

        await self.oldstop(*args, **kw)

        self.is_started = False

        await gather_helper(
            (listener.stop()
            for listener in self.listeners.values()), 
            (coordinated.stop()
            for coordinated in self.coordinateds.values()), 
            (history.stop()
            for history in self.histories.values()), 
            return_exc=True
        )

        
    def register_listener(self, listener: UpdateListener[UpdateType]) -> None:
        """
        Register a listener for its declared update type.

        Must be called before the dispatcher is started. Only one
        listener per update type is allowed.

        Parameters:
            listener: The :class:`UpdateListener` instance to register.

        Raises:
            RuntimeError: If the dispatcher is already running.
            ValueError:   If a listener for the same update type is
                          already registered.
        """

        if self.is_started:
            raise RuntimeError("Cannot register listener while dispatcher is already running")

        update_type = listener.__class__.__update_type__

        if update_type in self.listeners:
            raise ValueError(f"UpdateListener for {update_type!r} is already registered")

        self.listeners[update_type] = listener
    
    def register_coordinated(self, coordinated: UpdateCoordinated[UpdateType]) -> None:
        """
        Register a coordinated handler for its declared update type.

        Must be called before the dispatcher is started. Only one
        coordinated per update type is allowed.

        Parameters:
            coordinated: The :class:`UpdateCoordinated` instance to register.

        Raises:
            RuntimeError: If the dispatcher is already running.
            ValueError:   If a coordinated for the same update type is
                          already registered.
        """

        if self.is_started:
            raise RuntimeError("Cannot register coordinated while dispatcher is already running")

        update_type = coordinated.__class__.__update_type__

        if update_type in self.coordinateds:
            raise ValueError(f"UpdateCoordinated for {update_type!r} is already registered")

        self.coordinateds[update_type] = coordinated

    def register_history(self, history: UpdateHistory[UpdateType]) -> None:
        """
        Register a history handler for its declared update type.

        Must be called before the dispatcher is started. Only one
        history per update type is allowed.

        Parameters:
            history: The :class:`UpdateHistory` instance to register.

        Raises:
            RuntimeError: If the dispatcher is already running.
            ValueError:   If a history for the same update type is
                          already registered.
        """

        if self.is_started:
            raise RuntimeError("Cannot register history while dispatcher is already running")

        update_type = history.__class__.__update_type__

        if update_type in self.histories:
            raise ValueError(f"UpdateHistory for {update_type!r} is already registered")

        self.histories[update_type] = history

    async def unregister_listener(self, update_type: Type[PyroUpdate]) -> None:
        """
        Unregister and stop the listener for the given update type.

        Does nothing if no listener is registered for that type.

        Parameters:
            update_type: The Pyrogram update class whose listener should
                         be removed.
        """

        listener = self.listeners.pop(update_type, None)

        if listener is None:
            return

        await listener.stop()
    
    async def unregister_coordinated(self, update_type: Type[PyroUpdate]) -> None:
        """
        Unregister and stop the coordinated for the given update type.

        Does nothing if no coordinated is registered for that type.

        Parameters:
            update_type: The Pyrogram update class whose coordinated should
                         be removed.
        """

        coordinated = self.coordinateds.pop(update_type, None)

        if coordinated is None:
            return

        await coordinated.stop()

    async def unregister_history(self, update_type: Type[PyroUpdate]) -> None:
        """
        Unregister and stop the history for the given update type.

        Does nothing if no history is registered for that type.

        Parameters:
            update_type: The Pyrogram update class whose history should
                         be removed.
        """

        history = self.histories.pop(update_type, None)

        if history is None:
            return

        await history.stop()
    
    
    async def handle_listen(self, parsed_update: PyroUpdate) -> None:
        """
        Attempt to resolve the update against a registered listener.

        If a listener is found and resolves the update successfully,
        ``stop_propagation()`` is called on the update to prevent the
        normal handler pipeline from processing it further.

        Parameters:
            parsed_update: The parsed Pyrogram update to resolve.
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
        packet: Tuple[raw.base.Update, Dict[int, raw.base.User], Dict[int, raw.base.Chat]], 
        parsed_update: Optional[PyroUpdate], 
        handler_type: Type[Optional[PyroHandler]]
        ) -> Tuple[int, int]:
        """
        Process a single update through the listener and handler pipeline.

        First attempts to resolve the update via :meth:`handle_listen`,
        then iterates over handler groups, invoking the first matching
        handler per group.

        Parameters:
            packet:        The raw ``(update, users, chats)`` tuple from Pyrogram.
            parsed_update: The parsed Pyrogram update, or ``None`` if parsing
                           failed or was skipped.
            handler_type:  The handler class expected to handle this update.

        Returns:
            Tuple[int, int]: ``(handled_count, exc_count)`` — number of
            updates successfully handled and number that raised exceptions.
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
                        handler.callback, 
                        self.client, 
                        *args, 
                        executor=self.client.executor
                    )
                except StopPropagation:
                    raise
                except ContinuePropagation:
                    continue
                except Exception as exc:
                    exc_count += 1

                    await self.handle_update_handler_exception(
                        exc, handler, update, users, chats
                    )
                else:
                    handled_count += 1

                    if records is not None:
                        records.append(handler)

                break
        
        if records:
            try:
                await history.record_many(parsed_update, records, check=False)
            except Exception:
                log.exception("Unexpected error recording handlers for %r", parsed_update)

        return handled_count, exc_count
    
    async def handle_update(
        self, 
        packet: Tuple[raw.base.Update, Dict[int, raw.base.User], Dict[int, raw.base.Chat]], 
        parsed_update: Optional[PyroUpdate], 
        handler_type: Type[Optional[PyroHandler]]
        ) -> None:

        """
        Process a single update, acquiring a distributed lock if a
        coordinator is registered for its type.

        If no coordinator is registered, falls through to
        :meth:`_handle_update` immediately.

        If the lock is acquired, the update is processed and the lock
        is released with ``HANDLED`` if at least one handler succeeded
        without exceptions, or with ``None`` (allowing retry by another
        session) otherwise.

        If the lock is already held by another session, or acquiring
        the lock times out, the update is skipped silently.

        If acquiring the lock raises an unexpected exception, the update
        falls through to :meth:`_handle_update` without coordination.

        Parameters:
            packet:        The raw ``(update, users, chats)`` tuple from Pyrogram.
            parsed_update: The parsed Pyrogram update, or ``None``.
            handler_type:  The handler class expected to handle this update.
        """
        
        coordinated = self.coordinateds.get(type(parsed_update))

        if coordinated is None:
            await self._handle_update(packet, parsed_update, handler_type)
            return
        
        acquired = None

        try:
            acquired = await coordinated.acquire(parsed_update)
        except TimeoutError:
            acquired = False
            log.warning("Timeout waiting for coordinated lock on %s", parsed_update)
        except Exception:
            log.exception("Error while attempting to acquire coordinated lock")

        if acquired is None:
            await self._handle_update(packet, parsed_update, handler_type)
            return

        if not acquired:
            return 
        
        result = (0, 0)
        state = None
        
        try:
            result = await self._handle_update(packet, parsed_update, handler_type)
        except StopPropagation:
            state = UpdateLockState.HANDLED
            raise

        finally:
            if state is None and sum(result) >= 1:
                state = UpdateLockState.HANDLED
            
            await coordinated.release(parsed_update, state)
        

    async def handler_worker(self, lock):
        """
        Worker coroutine that consumes updates from the queue and
        dispatches them.

        Runs in a loop until a ``None`` sentinel is received. Each
        update is parsed and dispatched under an async lock to
        serialise concurrent workers.

        Parameters:
            lock: An async lock shared across all worker tasks to
                  serialise update processing.
        """

        while True:
            packet = await self.updates_queue.get()

            if packet is None:
                break

            try:
                update, users, chats = packet
                parsed_update, handler_type = (
                    await parser(update, users, chats)
                    if (parser := self.update_parsers.get(type(update))) is not None
                    else (None, type(None))
                )

                async with lock:
                    await self.handle_update(packet, parsed_update, handler_type)

            except StopPropagation:
                pass
            except Exception:
                log.exception("Unexpected error in handler_worker")