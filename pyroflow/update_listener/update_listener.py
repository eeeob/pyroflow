"""Base class for per-update-type listeners that back `ask` and `listen`."""

from __future__ import annotations as _annotations

import asyncio
from abc import ABC
from typing import Any, TYPE_CHECKING

from pytrove import maybe_awaitable

from ..typings import UpdateType
from ..utils import UpdateBound, get_update_executor
from ..errors import ListenerAlreadyExists, ListenerCancelled, ListenerTimeout
from ..enums import DuplicatePolicy
from ..models import ListenerKey, ListenerModel

if TYPE_CHECKING:
    from pytrove.typings import MaybeCoroutineCallable, Number, JsonValue as JsonValueT


class UpdateListener(ABC, UpdateBound[UpdateType]):
    """Abstract base that waits for updates of one Pyrogram type, keyed by `ListenerKey`.

    A subclass binds the update type with `__update_type__`. It decides how to
    key updates, and which ones to skip by returning `None`, either by
    overriding `extract_key` or through `extract_key_func`. A sync `*_func`
    runs in a thread, on the client's executor when it has one.

    Every waiting listener lives in this process: an update is matched only
    against the listeners of the client that received it.

    Args:
        duplicate_policy: What `listen` does when the key already has a
            waiting listener; `DuplicatePolicy.REPLACE` if `None`.
        extract_key_func: `(update) -> ListenerKey | None`, sync or async,
            used by `extract_key`; `None` skips the update.
        is_bypass_func: `(update) -> bool`, sync or async, used by `is_bypass`;
            if `None`, matched listeners are always resolved.
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
        ...     resolved = await listener.resolve(Message(id=7, chat=Chat(id=1)))
        ...     return resolved, (await waiter).id
        >>> asyncio.run(main())
        (True, 7)
    """

    def __init__(
        self,
        duplicate_policy: DuplicatePolicy | None = None,
        extract_key_func: MaybeCoroutineCallable[[UpdateType], ListenerKey | None] | None = None,
        is_bypass_func: MaybeCoroutineCallable[[UpdateType], bool] | None = None,
        timeout: Number | None = None,
        **kw: Any,
    ) -> None:
        """Initialise the listener; see the class docstring for the parameters."""
        super().__init__(**kw)

        if duplicate_policy is None:
            duplicate_policy = DuplicatePolicy.REPLACE

        self.duplicate_policy = duplicate_policy
        """What `listen` does when the key already has a waiting listener."""

        self.extract_key_func = extract_key_func
        """Optional key extractor behind `extract_key`."""
        self.is_bypass_func = is_bypass_func
        """Optional predicate behind `is_bypass`."""

        self.timeout = timeout
        """Default seconds `listen` waits; `None` waits indefinitely."""

        self.listeners: dict[ListenerKey, ListenerModel] = {}
        """Waiting listeners, by key."""
        self.is_closed = False
        """Whether `stop` ran since the last `start`; `listen` refuses to wait while it is."""

    async def start(self) -> None:
        """Accept `listen` calls again after a `stop`."""
        self.is_closed = False

    async def stop(self) -> None:
        """Refuse new `listen` calls and cancel every waiting listener."""
        self.is_closed = True

        for key in list(self.listeners):
            self.cancel(key)

    def cancel(self, key: ListenerKey, *, is_duplicate: bool = False) -> bool:
        """Cancel the listener waiting on `key`; its waiter gets `ListenerCancelled`.

        Args:
            key: The key identifying the listener.
            is_duplicate: Mark the cancellation as caused by a newer listener.

        Returns:
            Whether a listener was cancelled.

        Example:
            >>> from pyroflow.update_listener import MessageListener
            >>> async def main():
            ...     listener = MessageListener()
            ...     waiter = asyncio.create_task(listener.listen(1))
            ...     await asyncio.sleep(0)
            ...     cancelled = listener.cancel(ListenerKey(1))
            ...     try:
            ...         await waiter
            ...     except ListenerCancelled:
            ...         return cancelled
            >>> asyncio.run(main())
            True
        """
        listener = self.listeners.pop(key, None)

        if listener is None:
            return False

        if not listener.done():
            listener.set_exc(ListenerCancelled(key, is_duplicate=is_duplicate))

        return True

    async def listen(
        self,
        chat_id: int,
        user_id: int | None = None,
        message_id: int | None = None,
        meta: JsonValueT | None = None,
        *,
        prompt_id: int | None = None,
        timeout: Number | None = None,
    ) -> UpdateType:
        """Wait for the next update matching the given key.

        The listener is registered before this coroutine first yields, so it
        takes the first matching update the dispatcher handles after the
        call. Also callable as `listener(...)`.

        Args:
            chat_id: The chat to listen in.
            user_id: The user to wait for; `None` matches any user.
            message_id: The message to wait on; `None` matches any message.
            meta: Arbitrary metadata attached to the listener model.
            prompt_id: The message that asked for this update, stored as
                `ListenerModel.prompt_id`; `ask` passes the message it sent.
            timeout: Seconds to wait; `None` falls back to the listener's own
                `timeout`, and waits indefinitely when that is `None` too.

        Returns:
            The matching Pyrogram update.

        Raises:
            ListenerAlreadyExists: If a listener already waits on the key and
                `duplicate_policy` is `DuplicatePolicy.REJECT`.
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

        current = self.listeners.get(key)

        # A finished listener whose `listen` has not returned yet is no longer waiting.
        if current is not None and not current.done():
            if self.duplicate_policy is DuplicatePolicy.REJECT:
                raise ListenerAlreadyExists(key)

            self.cancel(key, is_duplicate=True)

        listener = ListenerModel(key, meta, prompt_id=prompt_id)
        self.listeners[key] = listener

        if timeout is None:
            timeout = self.timeout

        try:
            return await asyncio.wait_for(listener.future, timeout)
        except asyncio.TimeoutError:
            raise ListenerTimeout(key) from None
        finally:
            # A newer listener may have replaced this one under `key`.
            if self.listeners.get(key) is listener:
                del self.listeners[key]

    __call__ = listen
    """Alias of `listen`, so a listener can be awaited as `listener(...)`."""

    async def resolve(self, update: UpdateType) -> bool:
        """Give the update to the most specific listener waiting for it.

        Candidates are tried in the order of `ListenerKey.sub_keys`, from
        `(chat_id, user_id, message_id)` down to `(chat_id)`; the first one
        with a waiting listener takes the update. When `is_bypass` is true for
        the update, that listener is cancelled instead and the update goes on
        to the handlers.

        Args:
            update: The incoming Pyrogram update.

        Returns:
            Whether a listener took the update.

        Raises:
            TypeError: If `update` is not an instance of `__update_type__`.
        """
        key = await self.extract_key(update)

        if key is None:
            return False

        for sub in key.sub_keys():
            listener = self.listeners.get(sub)

            if listener is None or listener.done():
                continue

            if await self.is_bypass(update):
                self.cancel(sub)
                return False

            del self.listeners[sub]
            listener.resolve(update)
            return True

        return False

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

    async def is_bypass(self, update: UpdateType) -> bool:
        """Return whether a matched listener should be cancelled instead of resolved.

        Only called from `resolve`, after a waiting listener matched the
        update's key. On `True` that listener is cancelled and the update goes
        on to the normal handlers.

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
