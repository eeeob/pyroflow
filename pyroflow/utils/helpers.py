"""Internal helpers: an awaitable-release lock, the :class:`UpdateBound` base and ``ask`` error dispatch."""

from __future__ import annotations as _annotations

import asyncio
from abc import ABC
from typing import Any, Generic, TYPE_CHECKING

from pyrogram.types import Update as PyroUpdate
from pytrove import maybe_awaitable

from ..typings import UpdateType

if TYPE_CHECKING:
    from types import TracebackType

    from ..types import Message
    from ..typings import AskErrorHandlersT


class AsyncioLock(asyncio.Lock):
    """An :class:`asyncio.Lock` whose ``release`` is awaitable, matching :class:`AsyncLockProto`."""

    async def release(self) -> None:  # ty: ignore[invalid-method-override]  # deliberately async to match `AsyncLockProto`
        """Release the lock."""
        return super().release()

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        """Release the lock on leaving the ``async with`` block.

        Args:
            exc_type: The type of the exception that left the block, if any.
            exc: The exception that left the block, if any.
            tb: The traceback of that exception, if any.
        """
        await self.release()


class UpdateBound(Generic[UpdateType]):
    """Bind a class to a specific Pyrogram update type.

    Enforces that any concrete subclass declares a valid Pyrogram update
    type via ``__update_type__``, and provides a validation helper to ensure
    incoming updates match the declared type.

    This class is not meant to be used directly — inherit from it only.
    """

    __update_type__: type[UpdateType]
    """The Pyrogram update class this subclass is bound to."""

    def __init_subclass__(cls, **kw: Any) -> None:
        """Check that a concrete subclass declares a Pyrogram update type.

        Args:
            **kw: Passed on to the next base's ``__init_subclass__``.

        Raises:
            TypeError: If ``__update_type__`` is missing or is not a Pyrogram update class.
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
        """Check the declared update type again, then pass ``kw`` on to the next base.

        Args:
            **kw: Passed on to the next base's ``__init__``.

        Raises:
            TypeError: If ``__update_type__`` is missing or is not a Pyrogram update class.
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
        """Validate that the given update matches the declared ``__update_type__``.

        Args:
            update: The incoming Pyrogram update object.

        Raises:
            TypeError: If the update is not an instance of ``__update_type__``.
        """
        if not isinstance(update, cls.__update_type__):
            msg = f"Expected {cls.__update_type__.__name__}, got {type(update).__name__}"
            raise TypeError(msg)


async def handle_ask_error(
    exc: Exception,
    m: Message,
    *handlers: AskErrorHandlersT | None,
) -> bool:
    """Dispatch ``exc`` to the first matching entry across ``handlers``, awaited as ``handler(exc, m)``.

    Each mapping is scanned in order, and within a mapping its keys are tried in
    insertion order, so earlier ``handlers`` arguments take precedence — that is
    what makes ``ask(error_handlers=...)`` win over the client-wide
    :attr:`~pyroflow.Client.ask_error_handlers`. ``None`` and empty mappings are
    skipped, and the search stops at the first match.

    Handler failures are swallowed (``return_exc=True``): this runs from an
    ``except`` block whose original exception is about to be re-raised, and a
    failing handler must not replace it.

    Args:
        exc: The exception to dispatch.
        m: The message passed to the handler.
        *handlers: Mappings of exception types to handlers, highest precedence first.

    Returns:
        ``True`` if a handler matched and ran, ``False`` otherwise.
    """
    for hdlrs in handlers:
        if not hdlrs:
            continue

        for exc_types, handler in hdlrs.items():
            if isinstance(exc, exc_types):
                await maybe_awaitable(handler, exc, m, return_exc=True)
                return True

    return False


__all__ = (
    "AsyncioLock",
    "UpdateBound",
    "handle_ask_error",
)
