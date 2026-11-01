"""Internal typing helpers: the update type variable and the async lock protocol."""

from __future__ import annotations as _annotations
from typing import TYPE_CHECKING, Protocol, TypeVar
from pyrogram.types import Update as PyroUpdate

if TYPE_CHECKING:
    from types import TracebackType

UpdateType = TypeVar("UpdateType", bound=PyroUpdate)


class AsyncLockProto(Protocol):
    """An asyncio-style lock whose ``release`` is awaitable too."""

    async def acquire(self) -> bool:
        """Try to acquire the lock.

        Returns:
            ``True`` once the lock is held, or ``False`` if a bounded wait
            timed out.
        """

    async def release(self) -> None:
        """Release the lock."""

    async def __aenter__(self) -> object:
        """Acquire the lock on entering the ``async with`` block."""

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
        /,
    ) -> None:
        """Release the lock on leaving the ``async with`` block."""


__all__ = (
    "AsyncLockProto",
    "UpdateType",
)
