"""Internal lock helpers: an asyncio lock whose release is awaitable."""

from __future__ import annotations as _annotations
from typing import TYPE_CHECKING
import asyncio

if TYPE_CHECKING:
    from types import TracebackType


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


__all__ = ("AsyncioLock",)
