"""Patched Pyrogram dispatcher that offers each update to its listener before the handlers."""

from __future__ import annotations as _annotations

import asyncio
import logging
from contextlib import nullcontext, suppress
from typing import Any, TYPE_CHECKING

from pyrogram import StopPropagation, ContinuePropagation, raw
from pyrogram.dispatcher import Dispatcher as PyroDispatcher
from pyrogram.handlers import ErrorHandler, RawUpdateHandler, Handler as PyroHandler
from pytrove import gather_helper

from .enums import WorkersBusyMode
from .errors import ListenerWorkersBusy
from .models import WorkersPolicy
from .utils import call_maybe_async, handler_worker_var, patch_cls

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from pyrogram.types import Update as PyroUpdate

    from .models import ListenerKey, ListenerModel
    from .typings import UpdateType
    from .update_listener import UpdateListener


log = logging.getLogger(__name__)


@patch_cls(setter=setattr)
class Dispatcher(PyroDispatcher):
    """Pyrogram dispatcher extended with listeners.

    Patched onto `pyrogram.dispatcher.Dispatcher` in place, so every client uses
    it. A worker offers each parsed update to the listener registered for its
    type first, without the worker's lock; if the listener takes it, no
    handler runs. Otherwise `handle_update` runs the first matching handler
    of each group under the lock.
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

        self.workers_policy = WorkersPolicy()
        """What a wait inside a handler does when the workers run short."""
        self.handler_waits: list[WorkerWait] = []
        """The waits inside handlers that hold their worker, oldest first."""
        self.lent_worker_tasks: set[asyncio.Task[None]] = set()
        """The running stand-in workers lent to waits inside handlers."""
        self.worker_freed: asyncio.Event | None = None
        """Pulsed when a wait inside a handler ends; made by the first wait held by a `busy_timeout`."""

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

        if self.lent_worker_tasks:
            # A stand-in cancelled just after taking an update ends cancelled; it still did its work.
            await asyncio.gather(*self.lent_worker_tasks, return_exceptions=True)

        self.is_started = False

        return r

    def lacks_free_workers(self) -> bool:
        """Return whether one more wait holding its worker would leave too few free."""
        workers = self.client.workers
        return workers - len(self.handler_waits) - 1 < self.workers_policy.min_free_workers(workers)

    async def enter_handler_wait(
        self, listener: UpdateListener[Any], key: ListenerKey
    ) -> WorkerWait | None:
        """Apply `workers_policy` to a wait about to start inside a handler.

        Called by `UpdateListener.listen` from the worker task itself. The wait
        holds its worker unless that would leave fewer than
        `WorkersPolicy.free_workers` free; then, after up to its
        `busy_timeout` seconds for one to free, its `mode` steps in. With a
        `busy_timeout` above zero this yields, so an update can arrive before
        the wait is registered.

        Args:
            listener: The listener the wait is on.
            key: The key it waits on.

        Returns:
            The wait's handle, which `listen` sets the `model` of and
            releases when the wait ends; `None` with `WorkersBusyMode.NONE`,
            which tracks nothing.

        Raises:
            ListenerWorkersBusy: With `WorkersBusyMode.REJECT`, or with
                `WorkersBusyMode.CANCEL_OLDEST` when no wait holds a worker.
        """
        mode = self.workers_policy.mode

        if mode is WorkersBusyMode.NONE:
            return None

        wait = WorkerWait(self, listener, key)

        if not self.lacks_free_workers():
            self.handler_waits.append(wait)
            return wait

        if self.workers_policy.busy_timeout > 0:
            await self.wait_for_free_worker()

            if not self.lacks_free_workers():
                self.handler_waits.append(wait)
                return wait

        if mode is WorkersBusyMode.LEND:
            wait.lent = LentWorker(self)
            return wait

        if mode is WorkersBusyMode.CANCEL_OLDEST and self.handler_waits:
            oldest = self.handler_waits.pop(0)
            oldest.listener.evict(oldest.key, model=oldest.model)
            self.handler_waits.append(wait)
            return wait

        raise ListenerWorkersBusy(key)

    async def wait_for_free_worker(self) -> None:
        """Wait up to `WorkersPolicy.busy_timeout` seconds until a wait may hold its worker again."""
        loop = asyncio.get_running_loop()
        deadline = loop.time() + self.workers_policy.busy_timeout

        if self.worker_freed is None:
            self.worker_freed = asyncio.Event()

        while self.lacks_free_workers() and (remaining := deadline - loop.time()) > 0:
            try:
                await asyncio.wait_for(self.worker_freed.wait(), remaining)
            except asyncio.TimeoutError:
                return

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

    async def handle_listen(self, parsed_update: PyroUpdate) -> bool:
        """Offer the update to the listener registered for its type.

        A listener error is logged, and the update goes on to the handlers.

        Args:
            parsed_update: The parsed Pyrogram update to resolve.

        Returns:
            Whether the listener took the update, so no handler should run.
        """
        listener = self.listeners.get(type(parsed_update))

        if listener is None:
            return False

        try:
            return await listener.resolve(parsed_update)
        except Exception:
            log.exception("Unexpected error in handle_listen")
            return False

    async def handle_update(
        self,
        packet: tuple[raw.base.Update, dict[int, raw.base.User], dict[int, raw.base.Chat]],
        parsed_update: PyroUpdate | None,
        handler_type: type[PyroHandler | None],
        *,
        copy_groups: bool = False,
    ) -> None:
        """Run the first matching handler of each group.

        The listener already had the update (see `handler_worker`). A handler
        error is passed to `handle_update_handler_exception` and does not stop
        the other groups.

        Args:
            packet: The raw `(update, users, chats)` tuple from Pyrogram.
            parsed_update: The parsed Pyrogram update, or `None`.
            handler_type: The handler class expected to handle this update.
            copy_groups: Iterate copies of the groups, for a stand-in worker:
                it holds no lock, so `add_handler` may change them meanwhile.
                A worker holding its lock needs none, as registration waits
                for that lock.

        Raises:
            StopPropagation: If a handler stopped propagation.
        """
        update, users, chats = packet

        groups = list(self.groups.values()) if copy_groups else self.groups.values()

        for group in groups:
            for handler in list(group) if copy_groups else group:
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
                    await call_maybe_async(
                        handler.callback, self.client, *args, executor=self.client.executor
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

        A parsed update goes to `handle_listen` first, without the lock, so a
        listener resolves it whatever the handlers are doing. Errors are
        logged, never raised, so the worker keeps running.

        Args:
            lock: This worker's own lock; each update the listener does not
                take is handled while holding it.
        """
        await self.serve_updates(lock)

    async def serve_updates(
        self, lock: asyncio.Lock | None, lent: LentWorker | None = None
    ) -> None:
        """Run the worker loop of `handler_worker`, or of a stand-in worker.

        Args:
            lock: The worker's lock, or `None` for a stand-in, which holds none.
            lent: The stand-in this loop runs for; it stops once given back,
                and puts a `None` sentinel back for a real worker.
        """
        token = handler_worker_var.set((self, asyncio.current_task()))  # ty: ignore[invalid-argument-type]  # always called from a task

        try:
            while lent is None or not lent.given_back:
                if lent is not None:
                    lent.idle = True

                try:
                    packet = await self.updates_queue.get()
                finally:
                    if lent is not None:
                        lent.idle = False

                if packet is None:
                    if lent is not None:
                        self.updates_queue.put_nowait(None)
                    break

                try:
                    update, users, chats = packet
                    parsed_update, handler_type = (
                        await parser(update, users, chats)  # ty: ignore[invalid-argument-type]  # `kurigram`'s `update_parsers` is an untyped dict of differently-typed parsers, so ty infers their union
                        if (parser := self.update_parsers.get(type(update))) is not None
                        else (None, type(None))
                    )

                    if parsed_update is not None and await self.handle_listen(parsed_update):
                        continue

                    async with lock if lock is not None else nullcontext():
                        await self.handle_update(
                            packet, parsed_update, handler_type, copy_groups=lock is None
                        )
                except StopPropagation:
                    pass
                except Exception:
                    log.exception("Unexpected error in handler_worker")
        finally:
            handler_worker_var.reset(token)


class WorkerWait:
    """A wait inside a handler, as `Dispatcher.enter_handler_wait` tracks it."""

    __slots__ = ("dispatcher", "listener", "key", "model", "lent", "released")

    def __init__(
        self, dispatcher: Dispatcher, listener: UpdateListener[Any], key: ListenerKey
    ) -> None:
        """Track a wait of `listener` on `key`; see the class docstring."""
        self.dispatcher = dispatcher
        """The dispatcher whose worker runs the handler."""
        self.listener = listener
        """The listener the wait is on."""
        self.key = key
        """The key the wait is on."""
        self.model: ListenerModel | None = None
        """The registered wait, set by `listen`; `CANCEL_OLDEST` ends only this one."""
        self.lent: LentWorker | None = None
        """The stand-in worker lent to the wait, if any."""
        self.released = False
        """Whether `release` already ran."""

    def release(self) -> None:
        """End the tracking when the wait ends: free its slot, give back its stand-in, wake waiters."""
        if self.released:
            return

        self.released = True
        dispatcher = self.dispatcher

        with suppress(ValueError):  # a lent wait was never in the list
            dispatcher.handler_waits.remove(self)

        if self.lent is not None:
            self.lent.give_back()

        if (freed := dispatcher.worker_freed) is not None:
            freed.set()
            freed.clear()


class LentWorker:
    """A stand-in worker that serves the update queue while a handler waits."""

    __slots__ = ("given_back", "idle", "task")

    def __init__(self, dispatcher: Dispatcher) -> None:
        """Start the stand-in on `dispatcher`; see the class docstring."""
        self.given_back = False
        """Whether `give_back` ran; the loop stops after its current update."""
        self.idle = False
        """Whether the loop is waiting for an update, so it can be cancelled safely."""
        self.task = asyncio.get_running_loop().create_task(dispatcher.serve_updates(None, self))
        """The task running the stand-in loop."""

        dispatcher.lent_worker_tasks.add(self.task)
        self.task.add_done_callback(dispatcher.lent_worker_tasks.discard)

    def give_back(self) -> None:
        """Stop the stand-in: at once if idle (no update is lost), else after its current update."""
        self.given_back = True

        if self.idle:
            self.task.cancel()


__all__ = (
    "Dispatcher",
    "WorkerWait",
    "LentWorker",
)
