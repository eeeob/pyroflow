"""Internal helpers: the `UpdateBound` base, the update executor lookup and `ask` error dispatch."""

from __future__ import annotations as _annotations

from abc import ABC
from typing import Any, Generic, TYPE_CHECKING

from pyrogram.types import Update as PyroUpdate
from pytrove import maybe_awaitable

from ..typings import UpdateType

if TYPE_CHECKING:
    from concurrent.futures import ThreadPoolExecutor

    from ..types import Message
    from ..typings import AskErrorHandlersT


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
        >>> import asyncio
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


__all__ = (
    "UpdateBound",
    "get_update_executor",
    "handle_ask_error",
)
