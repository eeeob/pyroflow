from typing import Dict, Tuple, Type, Optional, Callable
from contextvars import ContextVar
from concurrent.futures import Future

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

from .errors import UnresolvedUpdate, UnhandledUpdate
from .enums import UpdateLockState
from .update_listener import UpdateListener
from .update_coordinated import UpdateCoordinated
from .update_history import UpdateHistory

import asyncio
import logging


log = logging.getLogger(__name__)


class _CoordinatedRelease:
    """
    Releases one update's coordinated lock, exactly once.

    Two callers compete for that single release: the handler, through
    :func:`mark_handled`, and :meth:`Dispatcher.handle_update` cleaning up once
    the handler returns. Whichever arrives first wins and the other becomes a
    no-op — which is what makes an early release *stick* instead of being
    overwritten by the automatic one a moment later.
    """

    __slots__ = ("_coordinated", "_update", "_loop", "_early")

    def __init__(
        self,
        coordinated: UpdateCoordinated,
        update: Optional[PyroUpdate],
        loop: asyncio.AbstractEventLoop,
        ) -> None:

        self._coordinated = coordinated
        self._update = update
        self._loop = loop
        self._early: Optional[Future] = None
        self._released: bool = False

    def claim_early(self) -> bool:
        """
        Claim the release now and schedule it. Backs :func:`mark_handled`.

        Synchronous out of necessity: the caller may be a sync handler running
        in the client's executor, off the event loop, where awaiting is not an
        option. Assigning ``_early`` *here* rather than inside the scheduled
        coroutine is what makes the claim race-free — by the time :meth:`settle`
        runs it already sees the release as spoken for, whether or not the loop
        has got round to performing it yet.

        Returns:
            ``True`` if this call took the release, ``False`` if it was already
            claimed.
        """

        if self._early is not None or self._released:
            return False

        self._early = asyncio.run_coroutine_threadsafe(
            self._release(UpdateLockState.HANDLED), self._loop
        )

        return True

    async def settle(self, state: Optional[UpdateLockState]) -> None:
        """Release with ``state``, or wait out an early release if one won."""

        if self._early is not None:
            # Don't abandon a release that is only scheduled: the dispatcher
            # may be stopped the moment the handler returns.
            await asyncio.wrap_future(self._early)
            return

        await self._release(state)

    async def _release(self, state: Optional[UpdateLockState]) -> None:
        if self._released:
            return

        self._released = True
        
        # Logged, never raised. The early release runs detached from the
        # handler, so an escaping exception would surface as a stray task error
        # rather than anywhere the caller could act on it — and a failing
        # backend should not produce two different outcomes depending on which
        # of the two paths happened to win.

        try:
            await self._coordinated.release(self._update, state)
        except Exception:
            log.exception("Failed to release coordinated lock for %r", self._update)


# Set for the duration of one coordinated update, to that update's
# _CoordinatedRelease. A ContextVar rather than an attribute on the update
# because copying the context is exactly what both `asyncio` tasks and
# `to_thread` already do — so a sync handler running in the executor, and a
# raw handler that never sees the parsed update at all, reach the same
# releaser as an ordinary async handler.
_handled_marker: ContextVar[Optional[_CoordinatedRelease]] = ContextVar(
    "pyroflow_handled_marker", default=None
)


def mark_handled() -> bool:
    """
    Declare the current update handled *now*, without waiting for the handler
    to return.

    By default the coordinated lock is held for the whole lifetime of the
    handler, and is only released — as :attr:`UpdateLockState.HANDLED` — once
    it finishes. That is the safe default, but it ties lock hold time to
    handler duration: a handler that runs a long job (a download, a
    conversation, an external API) keeps the lock for all of it, and every
    other session stays blocked on that chat meanwhile.

    Calling this from inside a handler decouples the two. The lock is released
    immediately with :attr:`UpdateLockState.HANDLED`, so peers stop waiting and
    will not reprocess the update, while the handler carries on for as long as
    it likes.

    Callable from a sync handler too (those run in the client's executor):
    the release is scheduled onto the event loop thread-safely rather than
    awaited here, which is also why this is a plain function and not a
    coroutine.

    Idempotent — later calls, and the automatic release when the handler
    returns, are no-ops.

    Example:
        .. code-block:: python

            @app.on_message()
            async def handler(client, message):
                await message.reply("Working on it...")

                mark_handled()          # peers are free from here on

                await slow_job()        # may take minutes; lock is long gone

    Returns:
        ``True`` if this call performed the early release. ``False`` if the
        update is not under a coordinator, its lock was already released, or
        this was called outside of update processing entirely.
    """

    release = _handled_marker.get()

    if release is None:
        return False

    return release.claim_early()


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
       The lock is released with :attr:`UpdateLockState.HANDLED` if at
       least one handler *ran* for this update — whether it returned
       normally or raised. A raising handler still counts as handled:
       the update reached its owner, so replaying it on another session
       would duplicate work rather than recover. The lock is released
       with ``None`` only when no handler ran at all, so another session
       can retry. A handler may cut the hold short by calling
       :func:`mark_handled`, which releases the lock as ``HANDLED``
       immediately and lets the handler keep running for as long as it
       needs.

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
    

    async def start(self, *args, **kw):
        """
        Start the dispatcher and all registered listeners, coordinators and histories.

        Parameters:
            *args: Passed directly to the original dispatcher.
            **kw: Passed directly to the original dispatcher.
        """

        r = await self.oldstart(*args, **kw)

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

        return r

    async def stop(self, *args, **kw):
        """
        Stop the dispatcher and all registered listeners, coordinators and histories.

        Parameters:
            *args: Passed directly to the original dispatcher.
            **kw: Passed directly to the original dispatcher.
        """

        r = await self.oldstop(*args, **kw)

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

        return r

        
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
                except (StopPropagation, UnhandledUpdate):
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
        is released with ``HANDLED`` if at least one handler ran —
        counting handlers that raised, since the update did reach its
        owner. It is released with ``None`` (allowing retry by another
        session) only when no handler ran at all.

        A handler can release the lock ahead of its own completion by
        calling :func:`mark_handled`; the automatic release then becomes a
        no-op. This keeps lock hold time bounded by how long the update
        takes to *claim*, not by how long it takes to *finish*.

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

        release = _CoordinatedRelease(
            coordinated, parsed_update, self.client.loop
        )
        token = _handled_marker.set(release)

        try:
            result = await self._handle_update(packet, parsed_update, handler_type)
        except StopPropagation:
            state = UpdateLockState.HANDLED
            raise

        finally:
            _handled_marker.reset(token)

            # sum() counts exc_count on purpose: a handler that raised still
            # *ran*, so the update reached its owner. Retrying it elsewhere
            # would duplicate work instead of recovering. Only a fully
            # untouched update (0 handled, 0 raised) is left for retry.
            if state is None and sum(result) >= 1:
                state = UpdateLockState.HANDLED

            # A no-op for `state` if the handler already claimed the release
            # through mark_handled().
            await release.settle(state)



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

            except (StopPropagation, UnhandledUpdate):
                pass
            except Exception:
                log.exception("Unexpected error in handler_worker")