"""Internal base classes: an awaitable-release asyncio lock and :class:`UpdateBound`."""

from __future__ import annotations as _annotations
from abc import ABC
from typing import TYPE_CHECKING, Any, Generic
from pyrogram.types import Update as PyroUpdate

from .typings import UpdateType

import asyncio

if TYPE_CHECKING:
    from types import TracebackType


class AsyncioLock(asyncio.Lock):
    """An :class:`asyncio.Lock` whose ``release`` is awaitable, matching :class:`AsyncLockProto`."""

    async def release(self) -> None:  # ty: ignore[invalid-method-override]  # deliberately async to match AsyncLockProto
        """Release the lock."""
        return super().release()

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        """Release the lock on leaving the ``async with`` block."""
        await self.release()


class UpdateBound(Generic[UpdateType]):
    """binds a class to a specific Pyrogram update type.

    Enforces that any concrete subclass declares a valid Pyrogram update
    type via __update_type__, and provides a validation helper to ensure
    incoming updates match the declared type.

    This class is not meant to be used directly — inherit from it only.

    Attributes:
        __update_type__: The Pyrogram update class this subclass is bound to.
    """

    __update_type__: type[UpdateType]

    def __init_subclass__(cls, **kw: Any) -> None:
        """Check that a concrete subclass declares a Pyrogram update type.

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
        """Validate that the given update matches the declared __update_type__.

        Parameters:
            update: The incoming Pyrogram update object.

        Raises:
            TypeError: If the update is not an instance of __update_type__.
        """
        if not isinstance(update, cls.__update_type__):
            msg = f"Expected {cls.__update_type__.__name__}, got {type(update).__name__}"
            raise TypeError(msg)


__all__ = (
    "AsyncioLock",
    "UpdateBound",
)
