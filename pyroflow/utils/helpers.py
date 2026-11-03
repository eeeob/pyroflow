"""Internal helpers: an awaitable-release lock, a Redis lock with a chosen value, the `UpdateBound` base and `ask` error dispatch."""

from __future__ import annotations as _annotations

import asyncio
from abc import ABC
from functools import cache
from typing import Any, Generic, TYPE_CHECKING

from pyrogram.types import Update as PyroUpdate
from pytrove import maybe_awaitable

from ..typings import UpdateType

if TYPE_CHECKING:
    from collections.abc import Callable
    from concurrent.futures import ThreadPoolExecutor
    from types import TracebackType

    from pytrove.typings import Number
    from redis.asyncio import Redis
    from redis.asyncio.lock import Lock

    from ..types import Message
    from ..typings import AskErrorHandlersT


class AsyncioLock(asyncio.Lock):
    """An `asyncio.Lock` whose `release` is awaitable, matching `AsyncLockProto`.

    Example:
        >>> async def main():
        ...     lock = AsyncioLock()
        ...     async with lock:
        ...         held = lock.locked()
        ...     return held, lock.locked()
        >>> asyncio.run(main())
        (True, False)
    """

    async def release(self) -> None:  # ty: ignore[invalid-method-override]  # deliberately async to match `AsyncLockProto`
        """Release the lock."""
        return super().release()

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        """Release the lock on leaving the `async with` block.

        Args:
            exc_type: The type of the exception that left the block, if any.
            exc: The exception that left the block, if any.
            tb: The traceback of that exception, if any.
        """
        await self.release()


class UpdateBound(Generic[UpdateType]):
    """Bind a class to a specific Pyrogram update type.

    Every subclass must set `__update_type__` to a Pyrogram `Update` subclass,
    except one that lists `ABC` directly among its bases. Inherit from it only;
    instantiating a class without `__update_type__` raises `TypeError`.

    Example:
        >>> from pyrogram.types import Message as PyroMessage
        >>> class MessageBound(UpdateBound[PyroMessage]):
        ...     __update_type__ = PyroMessage
        >>> MessageBound.validate_update("text")
        Traceback (most recent call last):
        ...
        TypeError: Expected Message, got str
    """

    __update_type__: type[UpdateType]
    """The Pyrogram update class this subclass is bound to."""

    def __init_subclass__(cls, **kw: Any) -> None:
        """Check that a concrete subclass declares a Pyrogram update type.

        Args:
            **kw: Passed on to the next base's `__init_subclass__`.

        Raises:
            TypeError: If `__update_type__` is missing or is not a Pyrogram update class.
        """
        super().__init_subclass__(**kw)

        if ABC in cls.__bases__:
            return

        if not hasattr(cls, "__update_type__"):
            msg = f"{cls.__name__} must define __update_type__"
            raise TypeError(msg)

        update_type = cls.__update_type__

        if not (isinstance(update_type, type) and issubclass(update_type, PyroUpdate)):
            msg = f"{cls.__name__}.__update_type__ must be a subclass of {PyroUpdate.__name__}"
            raise TypeError(msg)

    def __init__(self, **kw: Any) -> None:
        """Check the declared update type again, then pass `kw` on to the next base.

        Args:
            **kw: Passed on to the next base's `__init__`.

        Raises:
            TypeError: If `__update_type__` is missing or is not a Pyrogram update class.
        """
        update_type = getattr(self.__class__, "__update_type__", None)

        if update_type is None:
            msg = f"{self.__class__.__name__} must define __update_type__"
            raise TypeError(msg)

        if not (isinstance(update_type, type) and issubclass(update_type, PyroUpdate)):
            msg = (
                f"{self.__class__.__name__}.__update_type__ must be a subclass of "
                f"{PyroUpdate.__name__}"
            )
            raise TypeError(msg)

        super().__init__(**kw)

    @classmethod
    def validate_update(cls, update: UpdateType) -> None:
        """Validate that the given update matches the declared `__update_type__`.

        Args:
            update: The incoming Pyrogram update object.

        Raises:
            TypeError: If the update is not an instance of `__update_type__`.
        """
        if not isinstance(update, cls.__update_type__):
            msg = f"Expected {cls.__update_type__.__name__}, got {type(update).__name__}"
            raise TypeError(msg)


async def handle_ask_error(
    exc: Exception,
    m: Message,
    *handlers: AskErrorHandlersT | None,
) -> bool:
    """Run the first handler across `handlers` whose key matches `exc`, as `handler(exc, m)`.

    Mappings are scanned in order and their keys in insertion order, so earlier
    mappings take precedence; `None` and empty mappings are skipped. A sync
    handler runs in a worker thread. An exception raised by the handler is
    logged and swallowed, so it never replaces `exc`.

    Args:
        exc: The exception to dispatch.
        m: The message passed to the handler.
        *handlers: Mappings of exception types to handlers, highest precedence first.

    Returns:
        `True` if a handler matched and ran, `False` otherwise.

    Example:
        >>> seen = []
        >>> handlers = {ValueError: lambda exc, m: seen.append(m)}
        >>> asyncio.run(handle_ask_error(ValueError(), "message", None, handlers))
        True
        >>> seen
        ['message']
    """
    for hdlrs in handlers:
        if not hdlrs:
            continue

        for exc_types, handler in hdlrs.items():
            if isinstance(exc, exc_types):
                await maybe_awaitable(handler, exc, m, return_exc=True)
                return True

    return False


def get_update_executor(update: object) -> ThreadPoolExecutor | None:
    """Return the executor of the client bound to `update`.

    Args:
        update: The incoming update object.

    Returns:
        The client's `executor`, or `None` when the update carries no client
        or the client has no executor.

    Example:
        >>> get_update_executor(object()) is None
        True
    """
    return getattr(getattr(update, "_client", None), "executor", None)


@cache
def _redis_token_lock_class() -> Callable[..., Lock]:
    """Build, once, redis-py's async `Lock` extended to take its value in `__init__`.

    `redis` is an optional extra, so it is imported only when a caller that
    already holds a Redis client asks for a lock.
    """
    from redis.asyncio.lock import Lock  # noqa: PLC0415  # `redis` is an optional extra (CONTRIBUTING 2.6)

    class RedisTokenLock(Lock):
        """A redis-py async lock that writes `token` as its value on every acquisition."""

        def __init__(self, *args: Any, token: str, **kw: Any) -> None:
            """Create the lock; `token` is its value, the rest goes to redis-py's `Lock`."""
            super().__init__(*args, **kw)

            self.token = token
            """Value written to the lock key on acquisition."""

        async def acquire(
            self,
            blocking: bool | None = None,
            blocking_timeout: Number | None = None,
            token: str | bytes | None = None,
        ) -> bool:
            """Acquire the lock with `token`, defaulting to the one given at creation."""
            return await super().acquire(
                blocking, blocking_timeout, self.token if token is None else token
            )

    return RedisTokenLock


def redis_token_lock(redis: Redis, name: str, *, token: str, **kw: Any) -> Lock:
    """Build a redis-py async lock whose value is `token` instead of a random UUID.

    The value tells who holds the lock, so its owner can find it later. Keep
    `token` unique per lock: redis-py releases a lock only while its value
    still matches.

    Args:
        redis: The connected async Redis client.
        name: The Redis key of the lock.
        token: The value written to `name` on acquisition.
        **kw: Passed to redis-py's `Lock`, such as `timeout` or
            `blocking_timeout`.

    Returns:
        The lock, usable like any redis-py async lock.
    """
    return _redis_token_lock_class()(redis, name, token=token, **kw)


__all__ = (
    "AsyncioLock",
    "UpdateBound",
    "get_update_executor",
    "handle_ask_error",
    "redis_token_lock",
)
