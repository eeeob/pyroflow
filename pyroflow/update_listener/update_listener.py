"""Base class for per-update-type listeners that back `ask` and `listen`."""

from __future__ import annotations as _annotations

import asyncio
import logging
from abc import ABC
from typing import Any, TYPE_CHECKING

from pytrove import maybe_awaitable

from ..typings import UpdateType
from ..utils import UpdateBound, get_update_executor
from ..errors import ListenerAlreadyExists, ListenerCancelled, ListenerTimeout
from ..enums import DuplicatePolicy, ListenOutcome
from ..models import ListenerKey, ListenerModel
from ..update_coordinator import MemoryUpdateCoordinator, UpdateCoordinator

if TYPE_CHECKING:
    from pytrove.typings import MaybeCoroutineCallable, Number, JsonValue as JsonValueT

    from ..typings import CoordinatedUpdateKeyT


log = logging.getLogger(__name__)


class UpdateListener(ABC, UpdateBound[UpdateType]):
    """Abstract base that waits for updates of one Pyrogram type, keyed by `ListenerKey`.

    A subclass binds the update type with `__update_type__`. It decides how to
    key updates, and which ones to skip by returning `None`, either by
    overriding `extract_key` or through `extract_key_func`. A sync `*_func`
    runs in a thread, on the client's executor when it has one.

    The waiting futures live in this process. Every piece of shared state
    lives in the `coordinator`: the lock taken around a registration, and the
    registry of which session owns each key. Pass the same coordinator to the
    `UpdateCoordinated` of this update type: registering then takes the lock
    an update holds until it is settled, so an update is decided either fully
    before a registration or fully after it.

    Args:
        coordinator: The backend; a new `MemoryUpdateCoordinator` if `None`.
            It serves one listener only.
        duplicate_policy: What `listen` does when the key is already
            registered; `DuplicatePolicy.REPLACE` if `None`.
        extract_key_func: `(update) -> ListenerKey | None`, sync or async,
            used by `extract_key`; `None` skips the update.
        is_bypass_func: `(update) -> bool`, sync or async, used by `is_bypass`;
            if `None`, matched listeners are always resolved.
        extract_lock_key_func: `(key) -> lock key`, sync or async, used by
            `extract_lock_key`; if `None`, the chat of the key.
        timeout: Default seconds `listen` waits; `None` waits indefinitely.
        **kw: Passed to the next class in the MRO.

    Example:
        >>> from pyrogram.types import Chat, Message
        >>> class ChatListener(UpdateListener[Message]):
        ...     __update_type__ = Message
        >>> async def main():
        ...     listener = ChatListener(
        ...         extract_key_func=lambda update: ListenerKey(update.chat.id),
        ...     )
        ...     waiter = asyncio.create_task(listener.listen(1))
        ...     await asyncio.sleep(0)
        ...     outcome = await listener.resolve(Message(id=7, chat=Chat(id=1)))
        ...     return outcome, (await waiter).id
        >>> asyncio.run(main())
        (<ListenOutcome.RESOLVED: 'resolved'>, 7)
    """

    def __init__(
        self,
        coordinator: UpdateCoordinator | None = None,
        duplicate_policy: DuplicatePolicy | None = None,
        extract_key_func: MaybeCoroutineCallable[[UpdateType], ListenerKey | None] | None = None,
        is_bypass_func: MaybeCoroutineCallable[[UpdateType], bool] | None = None,
        extract_lock_key_func: MaybeCoroutineCallable[[ListenerKey], CoordinatedUpdateKeyT]
        | None = None,
        timeout: Number | None = None,
        **kw: Any,
    ) -> None:
        """Initialise the listener; see the class docstring for the parameters.

        Raises:
            ValueError: If `coordinator` handles another update type or already
                serves another listener.
        """
        super().__init__(**kw)

        update_type = self.__class__.__update_type__

        if coordinator is None:
            coordinator = MemoryUpdateCoordinator(update_type)
        elif coordinator.update_type is not update_type:
            msg = (
                f"{self.__class__.__name__} needs a coordinator for {update_type.__name__}, "
                f"got one for {coordinator.update_type.__name__}"
            )
            raise ValueError(msg)

        if coordinator.on_listener_lost is not None:
            msg = f"The {update_type.__name__} coordinator already serves another listener"
            raise ValueError(msg)

        coordinator.on_listener_lost = self.discard

        if duplicate_policy is None:
            duplicate_policy = DuplicatePolicy.REPLACE

        self.coordinator = coordinator
        """Backend holding the registration lock and the registry shared across sessions."""
        self.duplicate_policy = duplicate_policy
        """What `listen` does when the key is already registered."""

        self.extract_key_func = extract_key_func
        """Optional key extractor behind `extract_key`."""
        self.is_bypass_func = is_bypass_func
        """Optional predicate behind `is_bypass`."""
        self.extract_lock_key_func = extract_lock_key_func
        """Optional lock key extractor behind `extract_lock_key`."""

        self.timeout = timeout
        """Default seconds `listen` waits; `None` waits indefinitely."""

        self.listeners: dict[ListenerKey, ListenerModel] = {}
        """Waiting listeners of this process; the `coordinator` knows every session's."""
        self.is_closed = False
        """Whether `stop` ran since the last `start`; `listen` refuses to wait while it is."""

    async def start(self) -> None:
        """Accept `listen` calls again after a `stop`; the dispatcher starts the coordinator."""
        self.is_closed = False

    async def stop(self) -> None:
        """Refuse new `listen` calls and cancel every waiting listener of this process.

        The coordinator is left running: the dispatcher stops it once nothing
        uses it.
        """
        self.is_closed = True

        for key in list(self.listeners):
            self.discard(key)

    def discard(
        self, key: ListenerKey, owner_id: str | None = None, *, is_duplicate: bool = False
    ) -> bool:
        """Cancel the local listener for `key`, leaving the coordinator untouched.

        The waiter gets `ListenerCancelled`. The coordinator calls this when a
        peer took over or cancelled one of this session's registrations.

        Args:
            key: The key identifying the listener.
            owner_id: Only cancel the listener registered under this owner id,
                so a late report leaves a newer listener on the same key alone.
            is_duplicate: Mark the cancellation as caused by a newer listener.

        Returns:
            Whether a listener was cancelled.
        """
        listener = self.listeners.get(key)

        if listener is None or (owner_id is not None and listener.owner_id != owner_id):
            return False

        del self.listeners[key]

        if not listener.done():
            listener.set_exc(ListenerCancelled(key, is_duplicate=is_duplicate))

        return True

    async def cancel(self, key: ListenerKey) -> bool:
        """Cancel the listener for `key` in every session.

        The local waiter fails at once; a peer's waiter fails when that peer
        learns its registration is gone.

        Args:
            key: The key identifying the listener to cancel.

        Returns:
            Whether a listener was waiting here or registered anywhere.

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
        discarded = self.discard(key)
        removed = await self.coordinator.cancel_listener(key)

        return discarded or removed is not None

    def _forget(self, key: ListenerKey, listener: ListenerModel) -> None:
        """Drop `listener` from `listeners` unless a newer listener replaced it."""
        if self.listeners.get(key) is listener:
            del self.listeners[key]

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

        The listener is registered under the coordinator lock named by
        `extract_lock_key`. An update the dispatcher is processing holds the
        same lock until it is settled, so the listener takes only updates
        settled after it is registered. Also callable as `listener(...)`.

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
            ListenerAlreadyExists: If the key is already registered in any
                session and `duplicate_policy` is `DuplicatePolicy.REJECT`.
            ListenerTimeout: If the timeout expires before the update arrives.
            ListenerCancelled: If the listener is stopped, or is cancelled while
                waiting, including when a newer listener replaces it.

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

        if self.is_closed:
            raise ListenerCancelled(key)

        replace = self.duplicate_policy is DuplicatePolicy.REPLACE
        owner_id = self.coordinator.new_owner_id()

        async with self.coordinator.lock(await self.extract_lock_key(key)):
            if key in self.listeners:
                if not replace:
                    raise ListenerAlreadyExists(key)

                self.discard(key, is_duplicate=True)

            # Local first, so `resolve` never meets a registration of ours without its waiter.
            listener = ListenerModel(key, meta, owner_id=owner_id)
            self.listeners[key] = listener

            try:
                previous = await self.coordinator.register_listener(key, owner_id, replace=replace)

                if previous is not None and not replace:
                    if not self.coordinator.is_mine(previous):
                        raise ListenerAlreadyExists(key)

                    # No local waiter holds it, so it is a finished `listen` still unregistering.
                    await self.coordinator.register_listener(key, owner_id, replace=True)
            except BaseException:
                self._forget(key, listener)
                raise

        if timeout is None:
            timeout = self.timeout

        try:
            return await asyncio.wait_for(listener.future, timeout)
        except asyncio.TimeoutError:
            raise ListenerTimeout(key) from None
        finally:
            self._forget(key, listener)

            try:
                # Compare-and-delete: a newer registration under `key` survives.
                await self.coordinator.unregister_listener(key, owner_id)
            except Exception:
                log.exception("Failed to unregister the listener for %s", key)

    __call__ = listen
    """Alias of `listen`, so a listener can be awaited as `listener(...)`."""

    async def resolve(self, update: UpdateType) -> ListenOutcome:
        """Decide which listener, of any session, owns the update, and take it if it is ours.

        Candidates are tried in the order of `ListenerKey.sub_keys`, from
        `(chat_id, user_id, message_id)` down to `(chat_id)`, and the first one
        registered in the coordinator decides:

        - Owned by another session: `FOREIGN`, so this session leaves the
          update to it.
        - Owned by this session: its waiter gets the update, `RESOLVED`. A
          registration whose waiter already finished is skipped.
        - `is_bypass` true for the update: the matched listener is cancelled,
          wherever it waits, and the update goes on as `UNMATCHED`.

        With no key or no registered candidate the outcome is `UNMATCHED`. The
        dispatcher calls this while holding the update's coordination lock.

        Args:
            update: The incoming Pyrogram update.

        Returns:
            The outcome for the dispatcher.

        Raises:
            TypeError: If `update` is not an instance of `__update_type__`.
        """
        key = await self.extract_key(update)

        if key is None:
            return ListenOutcome.UNMATCHED

        sub_keys = list(key.sub_keys())
        owners = await self.coordinator.listener_owners(sub_keys)

        for sub, owner_id in zip(sub_keys, owners, strict=True):
            if owner_id is None:
                continue

            if not self.coordinator.is_mine(owner_id):
                if await self.is_bypass(update):
                    await self.coordinator.cancel_listener(sub)
                    return ListenOutcome.UNMATCHED

                return ListenOutcome.FOREIGN

            listener = self.listeners.get(sub)

            if listener is None or listener.owner_id != owner_id or listener.done():
                # A finished `listen` that has not unregistered yet.
                continue

            if await self.is_bypass(update):
                await self.cancel(sub)
                return ListenOutcome.UNMATCHED

            # The claim: only one update removes a registration.
            if await self.coordinator.unregister_listener(sub, owner_id) and not listener.done():
                listener.resolve(update)
                return ListenOutcome.RESOLVED

        return ListenOutcome.UNMATCHED

    async def extract_key(self, update: UpdateType) -> ListenerKey | None:
        """Extract the listener key of the update.

        Args:
            update: The incoming update object.

        Returns:
            The most specific key of the update, or `None` if it should not be
            listened to.

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

    async def extract_lock_key(self, key: ListenerKey) -> CoordinatedUpdateKeyT:
        """Return the coordinator lock `listen` registers `key` under.

        It must name the lock `UpdateCoordinated.extract_key` gives every
        update that can match `key`; otherwise an update may be decided while
        the listener registers. The default, the chat, matches the default of
        `MessageCoordinated` and `CallbackQueryCoordinated`.

        Args:
            key: The key `listen` is about to register.

        Returns:
            The lock key.

        Example:
            >>> from pyroflow.update_listener import MessageListener
            >>> asyncio.run(MessageListener().extract_lock_key(ListenerKey(1, 2, 3)))
            (1,)
        """
        if self.extract_lock_key_func is None:
            return (key.chat_id,)

        return await maybe_awaitable(  # ty: ignore[invalid-return-type]  # `pytrove` overloads cannot resolve `MaybeCoroutineCallable[..., T]` to `T`
            self.extract_lock_key_func, key, log_exc=False
        )

    async def is_bypass(self, update: UpdateType) -> bool:
        """Return whether a matched listener should be cancelled instead of resolved.

        Only called from `resolve`, after a registration matched the update's
        key. On `True` the matched listener is cancelled wherever it waits and
        the update goes on to the normal handlers. Every session must agree on
        it, so keep it a function of the update alone.

        Args:
            update: The incoming update object, already matched to a
                listener.

        Returns:
            `True` to cancel the matched listener, `False` to resolve it.
            Always `False` if neither this method is overridden nor
            `is_bypass_func` was provided.

        Raises:
            TypeError: If `is_bypass_func` is set and `update` is not an instance
                of `__update_type__`.
        """
        if self.is_bypass_func is None:
            return False

        self.validate_update(update)

        return await maybe_awaitable(  # ty: ignore[invalid-return-type]  # `pytrove` overloads cannot resolve `MaybeCoroutineCallable[..., T]` to `T`
            self.is_bypass_func,
            update,
            executor=get_update_executor(update),
            log_exc=False,
        )


__all__ = ("UpdateListener",)
