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
from ..typings import ListenerCoordinatorIdT
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

        bypass_func:
            Optional callable ``(update) -> bool`` used by
            :meth:`is_bypass`. Only consulted once a listener has
            already matched the update's key; returning ``True``
            cancels that listener instead of resolving it, letting the
            update fall through to the normal handler pipeline. If
            ``None`` (the default), matched listeners are always
            resolved and never bypassed.

        timeout:
            Optional timeout in seconds for listeners. If provided,
            it is used as the default duration after which a listener
            may be cancelled or expire.

        **kw:
            Passed to the next class in the MRO.
    """
    
    def __init__(
        self, 
        coordinator_factory: Optional[Callable[["UpdateListener"], ListenerCoordinator]] = None, 
        duplicate_policy: Optional[DuplicatePolicy] = None, 
        is_listenable_func: Optional[MaybeCoroutineCallable[[UpdateType], bool]] = None,
        extract_key_func: Optional[MaybeCoroutineCallable[[UpdateType], ListenerKey]] = None,
        bypass_func: Optional[MaybeCoroutineCallable[[UpdateType], bool]] = None,
        timeout: Optional[Number] = None,
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
        self.bypass_func = bypass_func

        self.timeout = timeout

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
        
    async def _cancel(
        self,
        key: ListenerKey,
        cancel_coordinator: bool = True,
        is_duplicate: bool = False,
        coordinator_id: Optional[ListenerCoordinatorIdT] = None,
        ) -> bool:
        """
        Cancel a listener by key, setting a :class:`ListenerCancelled`
        exception on its future.

        Parameters:
            key:             The key identifying the listener to cancel.
            cancel_coordinator: If ``True``, also cancel the distributed
                             coordinator entry.
            is_duplicate:    Marks the cancellation as caused by a newer
                             listener replacing this one, surfaced on the
                             raised :class:`ListenerCancelled`.
            coordinator_id:  If given, only cancel when the local listener
                             still holds this exact ownership token. Cancel
                             signals cross sessions asynchronously and can
                             arrive after the listener they targeted has
                             already finished and been replaced — without
                             this check a stale signal would cancel a newer,
                             perfectly valid listener that merely reuses the
                             same key.

        Returns:
            ``True`` if a local listener was cancelled, ``False`` if the key
            held nothing or held a different generation.
        """

        listener = self.listeners.get(key)

        if listener is not None:
            if coordinator_id is not None and listener.coordinator_id != coordinator_id:
                # A newer generation owns this key now — leave it running.
                log.debug(
                    "Ignoring stale cancel for %s: signal targets %r but %r is registered",
                    key, coordinator_id, listener.coordinator_id,
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
        coordinator_id: Optional[ListenerCoordinatorIdT] = None,
        ) -> bool:
        """
        Safely cancel a listener under the chat lock.

        All listener operations for the same chat share a single lock
        to avoid races between registration, cancellation and resolution.

        Parameters:
            key:             The key identifying the listener to cancel.
            cancel_coordinator: If ``True``, also cancel the distributed
                             coordinator entry.
            is_duplicate:    See :meth:`_cancel`.
            coordinator_id:  See :meth:`_cancel`.

        Returns:
            ``True`` if a local listener was cancelled.
        """

        async with self.coordinator.lock(key.chat_id):
            return await self._cancel(
                key, cancel_coordinator, is_duplicate, coordinator_id
            )

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
                    await self._cancel(key, is_duplicate=True)
                else:
                    raise TypeError(f"Unknown {self.duplicate_policy} duplicate_policy")
                
            elif key in self.listeners:
                raise RuntimeError("ListenerCoordinator and listeners are out of sync")
            

            fut = asyncio.get_running_loop().create_future()
            fut.add_done_callback(partial(self._cleanup_listen, key))

            listener = ListenerModel(key, meta, fut)
            
            # Acquire distributed ownership of this key. coordinator_id is
            # the generation token: it is later used to safely unregister
            # without removing a newer registration, to reject cancel signals
            # aimed at an older generation, and to prove ownership before
            # resolving an update (see _cancel and resolve).
            coordinator_id = await self.coordinator.register(key)
            listener.coordinator_id = coordinator_id
            self.listeners[key] = listener
        
        if timeout is None:
            timeout = self.timeout

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

            (chat_id, user_id, message_id)
            → (chat_id, user_id)
            → (chat_id, message_id)
            → (chat_id)

        The candidates are the *combinations* of the components the key
        carries, not merely its prefixes, so a listener registered as
        ``(chat_id, None, message_id)`` — "whoever answers this message" —
        is reachable. See :meth:`ListenerKey.sub_keys`.

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

            # Attempt progressively less specific matches, most specific
            # first — every combination of the components this key carries,
            # not just its prefixes. See ListenerKey.sub_keys().

            for sub in key.sub_keys():
                if listener := listeners.get(sub):
                    # A local listener is not proof of ownership. Another
                    # session may have taken this key over, and its cancel
                    # signal travels asynchronously — resolving on the strength
                    # of local state alone would let both sessions deliver the
                    # same update. Confirm we still hold the registration
                    # before handing the update over; this is the check that
                    # makes correctness independent of signal delivery.
                    if not await self.coordinator.registered(sub, listener.coordinator_id):
                        log.debug("Discarding superseded listener for %s (token %r)", sub, listener.coordinator_id,)
                        await self._cancel(sub, cancel_coordinator=False, coordinator_id=listener.coordinator_id)
                        continue

                    if await self.is_bypass(update):
                        # The update itself opts this listener out of
                        # resolving it (e.g. the user sent a bot command
                        # instead of the expected reply). Cancel the
                        # listener and treat the update as unresolved so
                        # handle_listen does not stop_propagation — the
                        # update falls through to the normal handler
                        # pipeline instead of being consumed here.
                        await self._cancel(sub, coordinator_id=listener.coordinator_id)
                        raise UnresolvedUpdate(update)

                    listener.resolve(update)
                    return

            # Called when no matching listener is found.
            await self.on_unresolved(key, update)
    
    async def on_unresolved(self, key: ListenerKey, update: UpdateType) -> None:
        """
        Called when no matching listener is found for an incoming update.

        Override to implement custom behaviour such as queuing or logging.
        By default raises :class:`UnresolvedUpdate`.

        .. warning::
            **This hook runs while the chat lock for ``key.chat_id`` is
            already held.** The lock is a plain :class:`asyncio.Lock`, so it
            is *not* reentrant: calling any public method of **this same
            listener** that takes the lock again — :meth:`cancel`,
            :meth:`listen`, :meth:`resolve` — deadlocks the worker
            permanently, with no timeout to recover from.

            Use the lock-free internals instead (:meth:`_cancel`), which is
            what this class does for its own bookkeeping. Calling into a
            *different* listener instance is safe: it owns a separate lock.

            .. code-block:: python

                async def on_unresolved(self, key, update):
                    await self._cancel(key)          # correct — no re-lock
                    # await self.cancel(key)         # DEADLOCK
                    return await super().on_unresolved(key, update)

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

    async def is_bypass(self, update: UpdateType) -> bool:
        """
        Determine whether a listener that already matched this update
        should be cancelled instead of resolved with it.

        Only called from :meth:`resolve`, after a listener has matched
        the update's key — never as a substitute for :meth:`is_listenable`.
        Returning ``True`` cancels the matched listener (raising
        :class:`~pyroflow.errors.ListenerCancelled` on its waiter) and the
        update is treated as unresolved, so :meth:`Dispatcher.handle_listen`
        does not call ``stop_propagation()``: the update falls through to
        the normal handler pipeline instead of being consumed here.

        Parameters:
            update: The incoming update object, already matched to a
                    listener.

        Returns:
            ``True`` to bypass (cancel) the matched listener, ``False``
            to resolve it normally. Always ``False`` if neither this
            method is overridden nor ``bypass_func`` was provided.
        """

        if self.bypass_func is None:
            return False

        self.validate_update(update)

        return await maybe_awaitable(
            self.bypass_func,
            update,
            executor=self._get_executor(update),
        )
