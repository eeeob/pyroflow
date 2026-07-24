from typing import (
    Collection as TCollection, Generator, Union, Reversible,
    Sequence, AbstractSet, Mapping, List, Any, Dict,
    Coroutine, Awaitable, TypeVar,
    Literal, TYPE_CHECKING,
)

from enum import Enum

import sys

if sys.version_info >= (3, 10):
    # typing.Callable only knows how to substitute a stdlib ParamSpec from
    # 3.10 onward; pairing it with a typing_extensions ParamSpec on older
    # versions raises "Parameters to generic types must be types" at
    # Callable[P, ...] substitution time (see audit finding C5).
    from typing import ParamSpec, TypeAlias, Protocol, Callable
else:
    from typing_extensions import ParamSpec, TypeAlias, Protocol, Callable

if sys.version_info >= (3, 11):
    from enum import EnumType
else:
    EnumType = type(Enum)

from pyrogram.types import Update as PyroUpdate


_P = ParamSpec("_P")
_T = TypeVar("_T")
_CT = TypeVar("_CT", bound=type)

_True = Literal[True]
_False = Literal[False]

P = ParamSpec("P")
R = TypeVar("R")
I = TypeVar("I")


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

NestedContainer: TypeAlias = Union[I, "Container[NestedContainer[I]]"]

MaybeCoroutineCallable: TypeAlias = Callable[P, Union[Coroutine[Any, Any, R], R]]
MaybeAwaitable: TypeAlias = Union[MaybeCoroutineCallable[P, R], Awaitable[R]]

NotContainer: TypeAlias = Union[bytearray, bytes, str, memoryview, EnumType]
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