"""Base class for per-update-type listeners that back `ask` and `listen`."""

from __future__ import annotations as _annotations

import asyncio
import inspect
from abc import ABC
from typing import Any, TYPE_CHECKING

from pytrove import maybe_awaitable

from ..typings import UpdateType
from ..utils import UpdateBound, get_update_executor
from ..errors import (
    ListenerAlreadyExists,
    ListenerCancelled,
    ListenerRejected,
    ListenerTimeout,
)
from ..enums import DuplicatePolicy
from ..models import ListenerKey, ListenerModel

if TYPE_CHECKING:
    from pyrogram.filters import Filter
    from pyrogram.types import Update as PyroUpdate
    from pytrove.typings import MaybeCoroutineCallable, Number, JsonValue as JsonValueT


def _combine(first: Filter | None, second: Filter | None) -> Filter | None:
    """Join two optional filters with `&`; a missing one leaves the other as it is.

    Example:
        >>> from pyrogram import filters
        >>> _combine(None, None) is None, _combine(filters.text, None) is filters.text
        (True, True)
    """
    if first is None:
        return second

    if second is None:
        return first

    return first & second


async def _passes(update_filter: Filter | None, update: PyroUpdate) -> bool:
    """Return whether `update` passes `update_filter`; no filter passes every update.

    The filter is called as `pyrogram.handlers.Handler.check` calls it: an
    async `__call__` is awaited, a sync one runs on the update client's
    executor.
    """
    if update_filter is None:
        return True

    client = update._client  # ty: ignore[unresolved-attribute]  # Pyrogram sets `_client` on every object in `Object.__init__`

    if inspect.iscoroutinefunction(update_filter.__call__):
        return bool(await update_filter(client, update))

    return bool(
        await asyncio.get_running_loop().run_in_executor(
            get_update_executor(update), update_filter, client, update
        )
    )


class UpdateListener(ABC, UpdateBound[UpdateType]):
    """Abstract base that waits for updates of one Pyrogram type, keyed by `ListenerKey`.

    A subclass binds the update type with `__update_type__`. It decides how to
    key updates, and which ones to skip by returning `None`, either by
    overriding `extract_key` or through `extract_key_func`. A sync `*_func`
    runs in a thread, on the client's executor when it has one.

    Every waiting listener lives in this process: an update is matched only
    against the listeners of the client that received it.

    A listener can also carry a Pyrogram filter. An update whose key matches
    but that fails the filter is skipped, and the listener keeps waiting; with
    `strict`, it ends the wait with `ListenerRejected` instead. See `listen`
    for the waits this can leave open.

    Args:
        duplicate_policy: What `listen` does when the key already has a
            waiting listener; `DuplicatePolicy.REPLACE` if `None`.
        extract_key_func: `(update) -> ListenerKey | None`, sync or async,
            used by `extract_key`; `None` skips the update.
        filters: A Pyrogram filter every `listen` adds to its own with `&`;
            `None` adds none.
        strict: The `strict` of a `listen` that does not pass one.
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
        filters: Filter | None = None,
        strict: bool = False,
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
        self.filters = filters
        """Filter every `listen` adds to its own with `&`, or `None`."""
        self.strict = strict
        """The `strict` of a `listen` that does not pass one."""

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
        filters: Filter | None = None,
        strict: bool | None = None,
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
            filters: A Pyrogram filter the update must pass besides its key,
                joined with the listener's own `filters` by `&`.
            strict: What an update whose key matches but that fails `filters`
                does: `True` ends the wait with `ListenerRejected`, `False`
                skips the update and keeps waiting. `None` uses the
                listener's `strict`.
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
            ListenerRejected: If `strict` is true and an update whose key
                matches fails `filters`; it carries that update.

        Warning:
            A wait that is not `strict` can stay open for good, until
            `timeout` or forever without one, when every update its key can
            still match fails `filters`:

            - The key names one update. A `MessageListener` key with a
              `message_id` names a single incoming message; if the filter
              rejects it, no other update can match.
            - The filter cannot pass this update type at all, such as a
              photo filter on a `CallbackQueryListener`.
            - The user keeps sending updates the filter rejects.

            Bound such waits with `timeout` (here or on the listener), pass
            `strict=True` when the first rejected update should end the wait,
            or end it with `cancel`. `strict=True` ends the wait on any
            rejected update of the key, such as a photo while text is
            awaited; catch `ListenerRejected` to ask again.

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

        listener = ListenerModel(
            key,
            meta,
            prompt_id=prompt_id,
            filters=_combine(self.filters, filters),
            strict=self.strict if strict is None else strict,
        )
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
        `(chat_id, user_id, message_id)` down to `(chat_id)`; the first
        waiting listener whose filter passes takes the update. A listener whose
        filter fails is skipped and keeps waiting, or, when `strict`, fails
        with `ListenerRejected`; either way the next candidate is tried.

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

            passed = await _passes(listener.filters, update)

            # The filter may yield; another update or a newer `listen` may have taken the slot.
            if self.listeners.get(sub) is not listener or listener.done():
                continue

            if not passed:
                if listener.strict:
                    del self.listeners[sub]
                    listener.set_exc(ListenerRejected(sub, update))

                continue

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


__all__ = ("UpdateListener",)
