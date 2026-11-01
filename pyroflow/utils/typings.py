from __future__ import annotations as _annotations
from typing import Protocol, Any, TypeVar
from pyrogram.types import Update as PyroUpdate

UpdateType = TypeVar("UpdateType", bound=PyroUpdate)


class AsyncLockProto(Protocol):
    async def acquire(self) -> bool: ...
    async def release(self) -> None: ...

    async def __aenter__(self) -> None: ...
    async def __aexit__(self, exc_type: Any, exc: Any, tb: Any) -> None: ...


__all__ = (
    "AsyncLockProto",
    "UpdateType",
)
