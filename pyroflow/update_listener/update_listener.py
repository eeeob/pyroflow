"""Base class for per-update-type listeners that back `ask` and `listen`."""

from __future__ import annotations as _annotations

import asyncio
import logging
from abc import ABC
from functools import partial
from typing import Any, TYPE_CHECKING

from pytrove import gather_helper, maybe_awaitable

from ..typings import UpdateType
from ..utils import UpdateBound, get_update_executor
from ..errors import ListenerAlreadyExists, ListenerCancelled, ListenerTimeout, UnresolvedUpdate
from ..enums import DuplicatePolicy
from ..models import ListenerKey, ListenerModel
from ..listener_coordinator import ListenerCoordinator, MemoryListenerCoordinator

if TYPE_CHECKING:
    from collections.abc import Callable

    from pytrove.typings import MaybeCoroutineCallable, Number, JsonValue as JsonValueT

    from ..typings import ListenerCoordinatorIdT


log = logging.getLogger(__name__)


class UpdateListener(ABC, UpdateBound[UpdateType]):
    """Abstract base that waits for updates of one Pyrogram type, keyed by `ListenerKey`.

    A subclass binds the update type with `__update_type__`. It decides which
    updates are listenable and how to key them, either by overriding
    `is_listenable` and `extract_key` or through `is_listenable_func` and
    `extract_key_func`. Listeners live in this process; ownership across
    sessions is delegated to the `ListenerCoordinator`. A sync `*_func` runs in
    a thread, on the client's executor when it has one.

    Args:
        coordinator_factory: Builds the coordinator from the listener;
            `MemoryListenerCoordinator` if `None`.
        duplicate_policy: What `listen` does when the key is already
            registered; `DuplicatePolicy.REPLACE` if `None`.
        is_listenable_func: `(update) -> bool`, sync or async, used by
            `is_listenable`.
        extract_key_func: `(update) -> ListenerKey`, sync or async, used by
            `extract_key`.
        bypass_func: `(update) -> bool`, sync or async, used by `is_bypass`;
            if `None`, matched listeners are always resolved.
        timeout: Default seconds `listen` waits; `None` waits indefinitely.
        **kw: Passed to the next class in the MRO.

    Example:
        >>> from pyrogram.types import Chat, Message
        >>> class ChatListener(UpdateListener[Message]):
        ...     __update_type__ = Message
        >>> async def main():
        ...     listener = ChatListener(
        ...         is_listenable_func=lambda update: True,
        ...         extract_key_func=lambda update: ListenerKey(update.chat.id),
        ...     )
        ...     waiter = asyncio.create_task(listener.listen(1))
        ...     await asyncio.sleep(0)
        ...     await listener.resolve(Message(id=7, chat=Chat(id=1)))
        ...     return (await waiter).id
        >>> asyncio.run(main())
        7
    """

    def __init__(
        self,
        coordinator_factory: Callable[[UpdateListener], ListenerCoordinator] | None = None,
        duplicate_policy: DuplicatePolicy | None = None,
        is_listenable_func: MaybeCoroutineCallable[[UpdateType], bool] | None = None,
        extract_key_func: MaybeCoroutineCallable[[UpdateType], ListenerKey] | None = None,
        bypass_func: MaybeCoroutineCallable[[UpdateType], bool] | None = None,
        timeout: Number | None = None,
        **kw: Any,
    ) -> None:
        """Initialize the listener; see the class docstring for the parameters."""
        super().__init__(**kw)

        if coordinator_factory is None:
            coordinator_factory = MemoryListenerCoordinator

        if duplicate_policy is None:
            duplicate_policy = DuplicatePolicy.REPLACE

        self.coordinator = coordinator_factory(self)
        """Backend that tracks listener ownership and locks across sessions."""
        self.duplicate_policy = duplicate_policy
        """What `listen` does when the key is already registered."""

        self.is_listenable_func = is_listenable_func
        """Optional predicate behind `is_listenable`."""
        self.extract_key_func = extract_key_func
        """Optional key extractor behind `extract_key`."""
        self.bypass_func = bypass_func
        """Optional predicate behind `is_bypass`."""

        self.timeout = timeout
        """Default seconds `listen` waits; `None` waits indefinitely."""

        self.listeners: dict[ListenerKey, ListenerModel] = {}
        """Local listeners owned by this process; the `coordinator` handles other sessions."""

    async def start(self) -> None:
        """Start the listener coordinator."""
        await self.coordinator.start()

    async def stop(self) -> None:
        """Cancel every local listener, then stop the coordinator.

        Logs a warning if any listener is still registered afterwards.
        """
        active = list(self.listeners.keys())

        await gather_helper(
            (self.cancel(key, cancel_coordinator=True) for key in active), return_exc=True
        )
        await self.coordinator.stop()

        if self.listeners:
            log.warning(
                "Stop %s UpdateListener completed with active listeners remaining: %s",
                self.__class__.__update_type__.__name__,
                list(self.listeners.keys()),
            )

    async def _cancel(
        self,
        key: ListenerKey,
        cancel_coordinator: bool = True,
        is_duplicate: bool = False,
        coordinator_id: ListenerCoordinatorIdT | None = None,
    ) -> bool:
        """Cancel a listener by key without taking the chat lock.

        The waiter gets `ListenerCancelled`. Use this instead of `cancel` when
        the lock for `key.chat_id` is already held.

        Args:
            key: The key identifying the listener to cancel.
            cancel_coordinator: Also cancel the coordinator entry.
            is_duplicate: Mark the cancellation as caused by a newer listener
                replacing this one, on the raised `ListenerCancelled`.
            coordinator_id: Only cancel if the local listener still holds this
                ownership token, so a late cancel signal from another session
                leaves a newer listener on the same key running.

        Returns:
            `False` only if `coordinator_id` was given and a different
            generation holds the key; `True` otherwise, including when no
            local listener existed.
        """
        listener = self.listeners.get(key)

        if listener is not None:
            if coordinator_id is not None and listener.coordinator_id != coordinator_id:
                # A newer generation owns this key now — leave it running.
                log.debug(
                    "Ignoring stale cancel for %s: signal targets %r but %r is registered",
                    key,
                    coordinator_id,
                    listener.coordinator_id,
                )
                return False

            self.listeners.pop(key, None)
            listener.set_exc(ListenerCancelled(key, is_duplicate=is_duplicate))

        if cancel_coordinator:
            await self.coordinator.cancel(key)

        return True

    async def cancel(
        self,
        key: ListenerKey,
        cancel_coordinator: bool = True,
        is_duplicate: bool = False,
        coordinator_id: ListenerCoordinatorIdT | None = None,
    ) -> bool:
        """Cancel a listener under the lock for `key.chat_id`.

        The lock is not reentrant: when it is already held, call `_cancel`
        instead.

        Args:
            key: The key identifying the listener to cancel.
            cancel_coordinator: Also cancel the coordinator entry.
            is_duplicate: See `_cancel`.
            coordinator_id: See `_cancel`.

        Returns:
            Same as `_cancel`.

        Example:
            >>> from pyroflow.update_listener import MessageListener
            >>> async def main():
            ...     listener = MessageListener()
            ...     waiter = asyncio.create_task(listener.listen(1))
            ...     await asyncio.sleep(0)
            ...     cancelled = await listener.cancel(ListenerKey(1))
            ...     try:
            ...         await waiter
            ...     except ListenerCancelled:
            ...         return cancelled
            >>> asyncio.run(main())
            True
        """
        async with self.coordinator.lock(ListenerKey(key.chat_id)):
            return await self._cancel(key, cancel_coordinator, is_duplicate, coordinator_id)

    def _cleanup_listen(self, key: ListenerKey, f: asyncio.Future) -> None:
        """Drop the listener for `key` once its future `f` completes.

        A newer listener that replaced it under the same key is kept.

        Args:
            key: The key identifying the listener.
            f: The future that just completed.
        """
        listener = self.listeners.get(key)

        if listener is not None and listener.future is f:
            self.listeners.pop(key)

    async def listen(
        self,
        chat_id: int,
        user_id: int | None = None,
        message_id: int | None = None,
        meta: JsonValueT | None = None,
        *,
        timeout: Number | None = None,
    ) -> UpdateType:
        """Wait for the next update matching the given key.

        Registers the listener locally and in the coordinator, and unregisters
        it when the wait ends for any reason. Also callable as `listener(...)`.

        Args:
            chat_id: The chat to listen in.
            user_id: The user to wait for; `None` matches any user.
            message_id: The message to wait on; `None` matches any message.
            meta: Arbitrary metadata attached to the listener model.
            timeout: Seconds to wait; `None` falls back to the listener's own
                `timeout`, and waits indefinitely when that is `None` too.

        Returns:
            The matching Pyrogram update.

        Raises:
            ListenerAlreadyExists: If the key is already registered and
                `duplicate_policy` is `DuplicatePolicy.REJECT`.
            ListenerTimeout: If the timeout expires before the update arrives.
            ListenerCancelled: If the listener is cancelled while waiting,
                including when a newer listener replaces it.

        Example:
            >>> from pyroflow.update_listener import MessageListener
            >>> async def main():
            ...     try:
            ...         await MessageListener().listen(1, timeout=0.01)
            ...     except ListenerTimeout as e:
            ...         return e.value
            >>> asyncio.run(main())
            ListenerKey(chat_id=1, user_id=None, message_id=None)
        """
        key = ListenerKey(chat_id, user_id, message_id)

        # One lock per chat serializes registration, cancellation and resolution.
        async with self.coordinator.lock(ListenerKey(key.chat_id)):
            # `registered` checks every session, not only `self.listeners`.
            if await self.coordinator.registered(key):
                if self.duplicate_policy == DuplicatePolicy.REJECT:
                    raise ListenerAlreadyExists(key)
                elif self.duplicate_policy == DuplicatePolicy.REPLACE:
                    await self._cancel(key, is_duplicate=True)
                else:
                    msg = f"Unknown {self.duplicate_policy} duplicate_policy"
                    raise TypeError(msg)

            elif key in self.listeners:
                msg = "ListenerCoordinator and listeners are out of sync"
                raise RuntimeError(msg)

            fut = asyncio.get_running_loop().create_future()
            fut.add_done_callback(partial(self._cleanup_listen, key))

            listener = ListenerModel(key, meta, fut)

            # `coordinator_id` is the generation token that `unregister`, `_cancel`
            # and `resolve` check, so an older generation never touches a newer one.
            coordinator_id = await self.coordinator.register(key)
            listener.coordinator_id = coordinator_id
            self.listeners[key] = listener

        if timeout is None:
            timeout = self.timeout

        try:
            return await asyncio.wait_for(fut, timeout)
        except asyncio.TimeoutError:
            exc = ListenerTimeout(key)
            if not listener.done():
                listener.set_exc(exc)
            raise exc from None
        except BaseException as e:
            if not listener.done():
                # `set_exc` يقبل `Exception` فقط، والـ `future` يقبل أي `BaseException`
                listener.future.set_exception(e)
            raise e

        finally:
            # `coordinator_id` keeps `unregister` from deleting a newer registration.
            self._cleanup_listen(key, fut)

            async with self.coordinator.lock(ListenerKey(key.chat_id)):
                await self.coordinator.unregister(key, coordinator_id)

    __call__ = listen
    """Alias of `listen`, so a listener can be awaited as `listener(...)`."""

    async def resolve(self, update: UpdateType) -> None:
        """Resolve the most specific pending listener matching the update.

        Candidates are tried in the order of `ListenerKey.sub_keys`, from
        `(chat_id, user_id, message_id)` down to `(chat_id)`. A listener whose
        registration another session has taken over is cancelled and the next
        candidate is tried. When none matches, including when this process
        holds no listeners, `on_unresolved` decides.

        Args:
            update: The incoming Pyrogram update.

        Raises:
            UnresolvedUpdate: If the update is not listenable, if `is_bypass`
                cancels the matched listener, or if no listener matches and
                `on_unresolved` raises it.
            TypeError: If `update` is not an instance of `__update_type__`.
        """
        if not await self.is_listenable(update):
            raise UnresolvedUpdate(update)

        key = await self.extract_key(update)
        listeners = self.listeners

        if listeners:
            # One lock per chat serializes registration, cancellation and resolution.
            async with self.coordinator.lock(ListenerKey(key.chat_id)):
                for sub in key.sub_keys():
                    if listener := listeners.get(sub):
                        # Another session may own this key while its cancel signal is
                        # still in flight; confirm ownership so only one session resolves.
                        if not await self.coordinator.registered(sub, listener.coordinator_id):
                            log.debug(
                                "Discarding superseded listener for %s (token %r)",
                                sub,
                                listener.coordinator_id,
                            )
                            await self._cancel(
                                sub,
                                cancel_coordinator=False,
                                coordinator_id=listener.coordinator_id,
                            )
                            continue

                        if await self.is_bypass(update):
                            # Unresolved, so `handle_listen` skips `stop_propagation`
                            # and the update reaches the normal handlers.
                            await self._cancel(sub, coordinator_id=listener.coordinator_id)
                            raise UnresolvedUpdate(update)

                        listener.resolve(update)
                        return

        await self.on_unresolved(key, update)

    async def on_unresolved(self, key: ListenerKey, update: UpdateType) -> None:
        """Handle an update that matched no listener; override to queue or log it.

        Runs after the lock for `key.chat_id` is released, so `cancel` is safe
        to call here; the lock-free `_cancel` is not.

        Args:
            key: The extracted key that had no matching listener.
            update: The incoming update that could not be resolved.

        Raises:
            UnresolvedUpdate: Always, unless overridden.
        """
        raise UnresolvedUpdate(update)

    async def is_listenable(self, update: UpdateType) -> bool:
        """Return whether this update should be listened to.

        Called before key extraction and before the chat lock is taken.

        Args:
            update: The incoming update object.

        Returns:
            `True` if the update should be listened to, `False` otherwise.

        Raises:
            NotImplementedError: If neither this method is overridden nor
                `is_listenable_func` was provided.
            TypeError: If `update` is not an instance of `__update_type__`.

        Example:
            >>> from pyrogram.types import Chat, Message
            >>> from pyroflow.update_listener import MessageListener
            >>> update = Message(id=1, chat=Chat(id=1), outgoing=True)
            >>> asyncio.run(MessageListener().is_listenable(update))
            False
        """
        if self.is_listenable_func is None:
            msg = (
                f"{self.__class__.__name__} must either pass is_listenable_func "
                f"or override is_listenable()"
            )
            raise NotImplementedError(msg)

        self.validate_update(update)

        return await maybe_awaitable(  # ty: ignore[invalid-return-type]  # `pytrove` overloads cannot resolve `MaybeCoroutineCallable[..., T]` to `T`
            self.is_listenable_func,
            update,
            executor=get_update_executor(update),
            log_exc=False,
        )

    async def extract_key(self, update: UpdateType) -> ListenerKey:
        """Extract the listener key of the update.

        Only called when `is_listenable` returns `True`.

        Args:
            update: The incoming update object.

        Returns:
            The most specific key of the update.

        Raises:
            NotImplementedError: If neither this method is overridden nor
                `extract_key_func` was provided.
            TypeError: If `update` is not an instance of `__update_type__`.

        Example:
            >>> from pyrogram.types import Chat, Message, User
            >>> from pyroflow.update_listener import MessageListener
            >>> update = Message(id=5, chat=Chat(id=1), from_user=User(id=2))
            >>> asyncio.run(MessageListener().extract_key(update))
            ListenerKey(chat_id=1, user_id=2, message_id=5)
        """
        if self.extract_key_func is None:
            msg = (
                f"{self.__class__.__name__} must either pass extract_key_func "
                f"or override extract_key()"
            )
            raise NotImplementedError(msg)

        self.validate_update(update)

        return await maybe_awaitable(  # ty: ignore[invalid-return-type]  # `pytrove` overloads cannot resolve `MaybeCoroutineCallable[..., T]` to `T`
            self.extract_key_func,
            update,
            executor=get_update_executor(update),
            log_exc=False,
        )

    async def is_bypass(self, update: UpdateType) -> bool:
        """Return whether a matched listener should be cancelled instead of resolved.

        Only called from `resolve`, after a listener matched the update's key.
        On `True` the waiter gets `ListenerCancelled` and `resolve` raises
        `UnresolvedUpdate`, so `Dispatcher.handle_listen` lets the update reach
        the normal handlers.

        Args:
            update: The incoming update object, already matched to a
                listener.

        Returns:
            `True` to cancel the matched listener, `False` to resolve it.
            Always `False` if neither this method is overridden nor
            `bypass_func` was provided.

        Raises:
            TypeError: If `bypass_func` is set and `update` is not an instance
                of `__update_type__`.
        """
        if self.bypass_func is None:
            return False

        self.validate_update(update)

        return await maybe_awaitable(  # ty: ignore[invalid-return-type]  # `pytrove` overloads cannot resolve `MaybeCoroutineCallable[..., T]` to `T`
            self.bypass_func,
            update,
            executor=get_update_executor(update),
            log_exc=False,
        )


__all__ = ("UpdateListener",)
