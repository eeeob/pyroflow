"""Base class for per-update-type listeners that back `ask` and `listen`."""

from __future__ import annotations as _annotations

import asyncio
from abc import ABC
from typing import TYPE_CHECKING

from pytrove import maybe_awaitable, is_exception

from ..typings import UpdateType
from ..utils import UpdateBound, get_update_executor
from ..errors import (
    ListenerAlreadyExists,
    ListenerCancelled,
    ListenerError,
    ListenerRejected,
    ListenerTimeout,
)
from ..enums import DuplicatePolicy, ListenerScope
from ..models import ListenerContext, ListenerKey, ListenerModel

if TYPE_CHECKING:
    from collections.abc import Callable

    from pyrogram.filters import Filter
    from pytrove.typings import MaybeCoroutineCallable, Number


class UpdateListener(ABC, UpdateBound[UpdateType]):
    """Abstract base that waits for updates of one Pyrogram type, keyed by `ListenerKey`.

    A subclass binds the update type with `__update_type__`. It decides how to
    key updates, and which ones to skip by returning `None`, either by
    overriding `extract_key` or through `extract_key_func`. A sync `*_func`
    runs in a thread, on the client's executor when it has one.

    Every waiting listener lives in this process: an update is matched only
    against the listeners of the client that received it.

    A `listen` can also carry a Pyrogram filter. An update whose key matches
    but that fails the filter is skipped, and the listener keeps waiting; with
    `strict`, it ends the wait with `ListenerRejected` instead. See `listen`
    for the waits this can leave open.

    Args:
        duplicate_policy: What `listen` does when the key already has a
            waiting listener; `DuplicatePolicy.REPLACE` if `None`.
        extract_key_func: `(update) -> ListenerKey | None`, sync or async,
            used by `extract_key`; `None` skips the update.
        on_error_func: `(exc, listener_model) -> object`, sync or async,
            called when a `ListenerError` ends a wait (a timeout, a
            cancellation or a strict rejection), after the wait is removed
            and before `listen` raises the error. Errors raised before a wait
            starts, such as `ListenerAlreadyExists`, are not reported. A
            failing callback is logged and never hides the error.
        on_listen_func: `(listen_kwargs) -> object`, called by `listen` with
            one dict of its arguments by name (`chat_id`, `user_id`,
            `message_id`, `context`, `filters`, `strict` and `timeout`, as
            passed) before the wait is registered; its result is ignored. It must be sync and
            fast, as it runs inline on the event loop; an error it raises
            propagates from `listen` and no wait starts.
        timeout: Default seconds `listen` waits; `None` waits indefinitely.
        resolve_scope: Which matching waits `resolve` gives an update to:
            `ListenerScope.FIRST` the most specific one, `ListenerScope.ALL`
            every one.
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
        on_error_func: MaybeCoroutineCallable[[ListenerError, ListenerModel], object] | None = None,
        on_listen_func: Callable[[dict[str, object]], object] | None = None,
        timeout: Number | None = None,
        resolve_scope: ListenerScope = ListenerScope.FIRST,
        **kw: object,
    ) -> None:
        """Initialise the listener; see the class docstring for the parameters."""
        super().__init__(**kw)

        if duplicate_policy is None:
            duplicate_policy = DuplicatePolicy.REPLACE

        self.duplicate_policy = duplicate_policy
        """What `listen` does when the key already has a waiting listener."""

        self.extract_key_func = extract_key_func
        """Optional key extractor behind `extract_key`."""
        self.on_error_func = on_error_func
        """Optional callback for the `ListenerError` that ends a wait."""
        self.on_listen_func = on_listen_func
        """Optional callback that sees the arguments of every `listen` call."""

        self.timeout = timeout
        """Default seconds `listen` waits; `None` waits indefinitely."""
        self.resolve_scope = resolve_scope
        """Which matching waits `resolve` gives an update to."""

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

    def reject(self, key: ListenerKey, update: UpdateType) -> bool:
        """End the listener waiting on `key` because `update` failed its filter.

        Its waiter gets `ListenerRejected`, which carries `update`.

        Args:
            key: The key identifying the listener.
            update: The update the listener's filter rejected.

        Returns:
            Whether a listener was rejected.

        Example:
            >>> from pyrogram.types import Message
            >>> from pyroflow.update_listener import MessageListener
            >>> async def main():
            ...     listener = MessageListener()
            ...     waiter = asyncio.create_task(listener.listen(1))
            ...     await asyncio.sleep(0)
            ...     rejected = listener.reject(ListenerKey(1), Message(id=2))
            ...     try:
            ...         await waiter
            ...     except ListenerRejected as e:
            ...         return rejected, e.update.id
            >>> asyncio.run(main())
            (True, 2)
        """
        listener = self.listeners.pop(key, None)

        if listener is None:
            return False

        if not listener.done():
            listener.set_exc(ListenerRejected(key, update))

        return True

    async def listen(
        self,
        chat_id: int,
        user_id: int | None = None,
        message_id: int | None = None,
        *,
        context: ListenerContext | None = None,
        filters: Filter | None = None,
        strict: bool = False,
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
            context: Values attached to the listener model; `None` attaches an
                empty `ListenerContext`.
            filters: A Pyrogram filter the update must pass besides its key.
            strict: What an update whose key matches but that fails `filters`
                does: `True` ends the wait with `ListenerRejected`, `False`
                skips the update and keeps waiting.
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
              rejects it, no other update can match. `MessageListener` logs a
              warning for such a wait through its default `on_listen_func`.
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

        if self.on_listen_func is not None:
            # Inline, not through `maybe_awaitable`: yielding here could let the awaited update slip past.
            self.on_listen_func(
                {
                    "chat_id": chat_id,
                    "user_id": user_id,
                    "message_id": message_id,
                    "context": context,
                    "filters": filters,
                    "strict": strict,
                    "timeout": timeout,
                }
            )

        current = self.listeners.get(key)

        # A finished listener whose `listen` has not returned yet is no longer waiting.
        if current is not None and not current.done():
            if self.duplicate_policy is DuplicatePolicy.REJECT:
                raise ListenerAlreadyExists(key)

            self.cancel(key, is_duplicate=True)

        future = asyncio.get_running_loop().create_future()
        self.listeners[key] = listener = ListenerModel(
            key,
            future,
            ListenerContext() if context is None else context,
            filters=filters,
            strict=strict,
        )

        if timeout is None:
            timeout = self.timeout

        error: ListenerError | None = None

        try:
            return await asyncio.wait_for(listener.future, timeout)
        except asyncio.TimeoutError:
            error = ListenerTimeout(key)
            raise error from None
        except ListenerError as exc:
            error = exc
            raise
        finally:
            # A newer listener may have replaced this one under `key`.
            if self.listeners.get(key) is listener:
                del self.listeners[key]

            if error is not None and (on_error := self.on_error_func) is not None:
                await maybe_awaitable(on_error, error, listener, return_exc=True, log_exc=True)

    __call__ = listen
    """Alias of `listen`, so a listener can be awaited as `listener(...)`."""

    async def resolve(self, update: UpdateType) -> bool:
        """Give the update to the waiting listeners it matches, as `resolve_scope` says.

        Candidates are tried in the order of `ListenerKey.sub_keys`, from
        `(chat_id, user_id, message_id)` down to `(chat_id)`. A waiting
        listener whose filter passes takes the update: with
        `ListenerScope.FIRST` only the first one does, with `ListenerScope.ALL`
        every one does. A listener whose filter fails, or raises (logged), is
        skipped and keeps waiting, or, when `strict`, fails with
        `ListenerRejected`; either way the next candidate is tried. A sync
        filter runs on the client's executor.

        Args:
            update: The incoming Pyrogram update.

        Returns:
            Whether at least one listener took the update.

        Raises:
            TypeError: If `update` is not an instance of `__update_type__`.
        """
        key = await self.extract_key(update)

        if key is None:
            return False

        took = False

        for sub in key.sub_keys():
            listener = self.listeners.get(sub)

            if listener is None or listener.done():
                continue

            if listener.filters is not None:
                passed = await maybe_awaitable(
                    listener.filters.__call__,
                    update._client,  # ty: ignore[unresolved-attribute]  # Pyrogram sets `_client` on every object in `Object.__init__`
                    update,
                    executor=get_update_executor(update),
                    return_exc=True,
                    log_exc=True,
                )

                # The filter may yield; another update or a newer `listen` may have taken the slot.
                if self.listeners.get(sub) is not listener or listener.done():
                    continue

                if is_exception(passed) or not passed:
                    if listener.strict:
                        self.reject(sub, update)

                    continue

            del self.listeners[sub]
            listener.resolve(update)
            took = True

            if self.resolve_scope is ListenerScope.FIRST:
                break

        return took

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
