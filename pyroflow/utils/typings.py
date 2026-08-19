from typing import Protocol, Any, List, TypeAlias, TypeVar, Union
from pyrogram.types import Update as PyroUpdate

from pytrove.typings import *
from pytrove.typings import __all__ as _pytrove_all

UpdateType = TypeVar("UpdateType", bound=PyroUpdate)

class AsyncLockProto(Protocol):
    async def acquire(self) -> bool: ...
    async def release(self) -> None: ...

    async def __aenter__(self) -> None: ...
    async def __aexit__(self, exc_type: Any, exc: Any, tb: Any) -> None: ...

MaybeList: TypeAlias = Union[_T, List[_T]]


__all__ = (
    *_pytrove_all,
    "AsyncLockProto",
    "UpdateType",
    "MaybeList",
)
