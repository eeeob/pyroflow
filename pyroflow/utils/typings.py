from typing import (
    Collection as TCollection, Generator, Union, Reversible, 
    Sequence, AbstractSet, Mapping, List, Any, Dict, 
    Coroutine, Awaitable, TypeVar, 
    Literal, ParamSpec, TypeAlias, Protocol, Callable, 
    TYPE_CHECKING, 
)

from enum import EnumMeta as EnumType
from pyrogram.types import Update as PyroUpdate


_P = ParamSpec("_P")
_T = TypeVar("_T")
_CT = TypeVar("_CT", bound=type)

_True = Literal[True]
_False = Literal[False]


if TYPE_CHECKING:
    Container: TypeAlias = Union[
        Generator[_T, Any, Any], TCollection[_T], Reversible[_T], 
        Sequence[_T], AbstractSet[_T], Mapping[_T, Any], 
        filter, enumerate, zip
    ]
else:
    Container = Union[
        Generator, TCollection, Reversible, 
        Sequence, AbstractSet, Mapping, 
        filter, enumerate, zip
    ]

NestedContainer: TypeAlias = Union[_T, "Container[NestedContainer[_T]]"]
NotContainer: TypeAlias = Union[bytearray, bytes, str, memoryview, EnumType]

MaybeCoroutineCallable: TypeAlias = Callable[_P, Union[Coroutine[Any, Any, _T], _T]]
MaybeAwaitable: TypeAlias = Union[MaybeCoroutineCallable[_P, _T], Awaitable[_T]]

Number: TypeAlias = Union[int, float]

JsonValueT: TypeAlias = Union[
    int, float, str, bool, None, 
    List["JsonValueT"], 
    Dict[str, "JsonValueT"]
]


class AsyncLockProto(Protocol):
    async def acquire(self) -> bool: ...
    async def release(self) -> None: ...

    async def __aenter__(self) -> None: ...
    async def __aexit__(self, exc_type: Any, exc: Any, tb: Any) -> None: ...


UpdateType = TypeVar("UpdateType", bound=PyroUpdate)


__all__ = (
    "Container",
    "NestedContainer",
    "NotContainer",
    "MaybeAwaitable",
    "Number",
    "MaybeCoroutineCallable",
    "AsyncLockProto",
    "JsonValueT",
    "UpdateType",
    "_P", "_T", "_CT",
    "_True", "_False",
)