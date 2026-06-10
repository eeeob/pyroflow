from typing import Optional, Callable, Dict
from abc import ABC
from functools import partial
from concurrent.futures import ThreadPoolExecutor

from ..utils.typings import MaybeCoroutineCallable, Number, JsonValueT, UpdateType
from ..utils import gather_helper, maybe_awaitable, UpdateBound

from ..errors import (
    ListenerCancelled, 
    ListenerTimeout, 
    ListenerAlreadyExists, 
    UnresolvedUpdate
)


from ..enums import DuplicatePolicy
from ..models import ListenerModel, ListenerKey
from ..listener_coordinator import ListenerCoordinator, MemoryListenerCoordinator

import logging
import asyncio


log = logging.getLogger(__name__)



class UpdateListener(ABC, UpdateBound[UpdateType]):
    """
    Abstract base for per-update-type listener management.

    Each subclass is bound to a single Pyrogram update type via
    ``__update_type__`` and defines how to determine whether an update
    should be listened to, as well as how to extract its
    :class:`ListenerKey`.

    Listeners are stored locally within the process, while optional
    cross-process coordination (e.g. Redis-backed ownership and
    cancellation propagation) is delegated to a
    :class:`ListenerCoordinator`.

    The two core behaviours — listenability check and key extraction —
    can be provided either by overriding the corresponding methods in a
    subclass, or by passing callables at construction time via
    ``is_listenable_func`` and ``extract_key_func``.

    Parameters:
        coordinator_factory:
            Optional callable receiving the listener instance and
            returning a configured :class:`ListenerCoordinator`.
            If ``None``, a :class:`MemoryListenerCoordinator`
            will be used.

        duplicate_policy:
            Policy used when registering a listener whose key is already
            in use. If ``None``, :attr:`DuplicatePolicy.REPLACE`
            is used.

        is_listenable_func:
            Optional callable ``(update) -> bool`` used by
            :meth:`is_listenable`. If ``None``, the method must be
            overridden in a subclass.

        extract_key_func:
            Optional callable ``(update) -> ListenerKey`` used by
            :meth:`extract_key`. If ``None``, the method must be
            overridden in a subclass.

        **kw:
            Passed to the next class in the MRO.
    """
    
    def __init__(
        self, 
        coordinator_factory: Optional[Callable[["UpdateListener"], ListenerCoordinator]] = None, 
        duplicate_policy: Optional[DuplicatePolicy] = None, 
        is_listenable_func: Optional[MaybeCoroutineCallable[[UpdateType], bool]] = None, 
        extract_key_func: Optional[MaybeCoroutineCallable[[UpdateType], ListenerKey]] = None, 
        **kw
        ) -> None:

        super().__init__(**kw)

        if coordinator_factory is None:
            coordinator_factory = MemoryListenerCoordinator
        
        if duplicate_policy is None:
            duplicate_policy = DuplicatePolicy.REPLACE
        
        self.coordinator = coordinator_factory(self)
        self.duplicate_policy = duplicate_policy

        self.is_listenable_func = is_listenable_func
        self.extract_key_func = extract_key_func

        # Local listeners currently owned by this process.
        # Cross-process coordination is handled by the coordinator.
        self.listeners: Dict[ListenerKey, ListenerModel] = {}

    async def start(self) -> None:
        await self.coordinator.start()

    async def stop(self):
        active = list(self.listeners.keys())

        await gather_helper(
            (self.cancel(key, cancel_coordinator=True)
            for key in active), 
            return_exc=True
        )
        await self.coordinator.stop()

        if self.listeners:
            log.warning(
                "Stop %s UpdateListener completed with active listeners remaining: %s", 
                self.__class__.__update_type__.__name__, 
                list(self.listeners.keys())
                )
        
    async def _cancel(self, key: ListenerKey, cancel_coordinator: bool = True) -> None:
        """
        Cancel a listener by key, setting a :class:`ListenerCancelled`
        exception on its future.

        Parameters:
            key:             The key identifying the listener to cancel.
            cancel_coordinator: If ``True``, also cancel the distributed
                             coordinator entry.
        """

        if (listener := self.listeners.pop(key, None)) is not None:
            listener.set_exc(ListenerCancelled(key))
        
        if cancel_coordinator:
            await self.coordinator.cancel(key)

    async def cancel(self, key: ListenerKey, cancel_coordinator: bool = True) -> None:
        """
        Safely cancel a listener under the chat lock.

        All listener operations for the same chat share a single lock
        to avoid races between registration, cancellation and resolution.

        Parameters:
            key:             The key identifying the listener to cancel.
            cancel_coordinator: If ``True``, also cancel the distributed
                             coordinator entry.
        """

        async with self.coordinator.lock(key.chat_id):
            await self._cancel(key, cancel_coordinator)

    def _cleanup_listen(self, key: ListenerKey, f: asyncio.Future) -> None:
        """
        Done callback attached to each listener future.

        Removes the listener from ``self.listeners`` when its future
        completes, unless it has already been replaced by a newer one.

        Parameters:
            key: The key identifying the listener.
            f:   The future that just completed.
        """

        listener = self.listeners.get(key)

        if listener is not None and listener.future is f:
            self.listeners.pop(key)

    async def listen(
        self, 
        chat_id: int, 
        user_id: Optional[int] = None, 
        message_id: Optional[int] = None, 
        meta: Optional[JsonValueT] = None, 
        *, 
        timeout: Optional[Number] = None, 
        ) -> UpdateType:

        """
        Wait for the next update matching the given key.

        Registers a listener locally and in the distributed coordinator,
        then suspends until a matching update arrives or the timeout
        expires.

        Parameters:
            chat_id:    The chat to listen in.
            user_id:    Optional user to filter by.
            message_id: Optional message to filter by.
            meta:       Arbitrary metadata attached to the listener model.
            timeout:    Seconds to wait before raising :class:`ListenerTimeout`.
                        ``None`` waits indefinitely.

        Returns:
            The matching Pyrogram update.

        Raises:
            ListenerAlreadyExists: If a listener for the same key exists and
                                   ``duplicate_policy`` is ``REJECT``.
            ListenerTimeout:       If the timeout expires before the update arrives.
            ListenerCancelled:     If the listener is cancelled while waiting.
        """

        
        key = ListenerKey(chat_id, user_id, message_id)

        # All listener operations for the same chat share
        # a single lock to avoid races between registration,
        # cancellation and update resolution.
        async with self.coordinator.lock(key.chat_id):
            # Prevent multiple listeners from registering the same key
            # across local and distributed processes.

            if await self.coordinator.registered(key):
                if self.duplicate_policy == DuplicatePolicy.REJECT:
                    raise ListenerAlreadyExists(key)
                elif self.duplicate_policy == DuplicatePolicy.REPLACE:
                    await self._cancel(key)
                else:
                    raise TypeError(f"Unknown {self.duplicate_policy} duplicate_policy")
                
            elif key in self.listeners:
                raise RuntimeError("ListenerCoordinator and listeners are out of sync")
            

            fut = asyncio.get_running_loop().create_future()
            fut.add_done_callback(partial(self._cleanup_listen, key))

            listener = ListenerModel(key, meta, fut)
            
            # Acquire distributed ownership of this key.
            # coordinator_id is later used to safely unregister
            # without removing a newer registration.
            coordinator_id = await self.coordinator.register(key)
            self.listeners[key] = listener

        try:
            # Wait until the listener is resolved or cancelled.
            return await asyncio.wait_for(fut, timeout)
        except asyncio.TimeoutError as e:
            exc = ListenerTimeout(key)
            if not listener.done():
                listener.set_exc(exc)
            raise exc from e
        except BaseException as e:
            if not listener.done():
                listener.set_exc(e)
            raise
            
        finally:

            # Release distributed ownership.
            # The coordinator_id prevents deleting a newer registration
            # that may have replaced this one.

            self._cleanup_listen(key, fut)

            async with self.coordinator.lock(key.chat_id):
                await self.coordinator.unregister(key, coordinator_id)

    __call__ = listen

    async def resolve(self, update: UpdateType) -> None:
        """
        Resolve a pending listener with the given update.

        Validates the update type, extracts its key, then attempts to
        match it against registered listeners using progressively less
        specific keys:

            (chat_id, user_id, message_id) → (chat_id, user_id) → (chat_id)

        Parameters:
            update: The incoming Pyrogram update.

        Raises:
            UnresolvedUpdate: If no matching listener is found and
                              :meth:`on_unresolved` re-raises.
        """

        if not await self.is_listenable(update):
            raise UnresolvedUpdate(update)

        key = await self.extract_key(update)
        listeners = self.listeners

        # All listener operations for the same chat share
        # a single lock to avoid races between registration,
        # cancellation and update resolution.
        async with self.coordinator.lock(key.chat_id):

            # Attempt progressively less specific matches:
            # (chat_id, user_id, message_id)
            # (chat_id, user_id)
            # (chat_id)

            for sub in key.sub_keys():
                if listener := listeners.get(sub):
                    listener.resolve(update)
                    return

            # Called when no matching listener is found.
            await self.on_unresolved(key, update)
    
    async def on_unresolved(self, key: ListenerKey, update: UpdateType) -> None:
        """
        Called when no matching listener is found for an incoming update.

        Override to implement custom behaviour such as queuing or logging.
        By default raises :class:`UnresolvedUpdate`.

        Parameters:
            key:    The extracted key that had no matching listener.
            update: The incoming update that could not be resolved.

        Raises:
            UnresolvedUpdate: Always, unless overridden.
        """
        raise UnresolvedUpdate(update)

    def _get_executor(self, update: UpdateType) -> Optional[ThreadPoolExecutor]:
        return getattr(
            getattr(update, "_client", None), 
            "executor", 
            None
        )
    
    async def is_listenable(self, update: UpdateType) -> bool:
        """
        Determine whether this update should be listening.

        Called before any key extraction or lock acquisition.

        Parameters:
            update: The incoming update object.

        Returns:
            ``True`` if the update should be listening, ``False`` otherwise.

        Raises:
            NotImplementedError: If neither this method is overridden nor
                                 ``is_listenable_func`` was provided.
        """

        if self.is_listenable_func is None:
            raise NotImplementedError(
                f"{self.__class__.__name__} must either pass is_listenable_func "
                f"or override is_listenable()"
            )
        
        self.validate_update(update)

        return await maybe_awaitable(
            self.is_listenable_func,
            update,
            executor=self._get_executor(update),
        )

    async def extract_key(self, update: UpdateType) -> ListenerKey:
        """
        Extract a unique listener key from the update.

        Only called when :meth:`is_listenable` returns ``True``.

        Parameters:
            update: The incoming update object.

        Returns:
            A :data:`ListenerKey` that uniquely identifies
            this update.

        Raises:
            NotImplementedError: If neither this method is overridden nor
                                 ``extract_key_func`` was provided.
        """

        if self.extract_key_func is None:
            raise NotImplementedError(
                f"{self.__class__.__name__} must either pass extract_key_func "
                f"or override extract_key()"
            )
        
        self.validate_update(update)

        return await maybe_awaitable(
            self.extract_key_func,
            update,
            executor=self._get_executor(update),
        )
