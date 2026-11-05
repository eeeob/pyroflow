"""Internal helpers: the `UpdateBound` base, the update executor lookup and subsets."""

from __future__ import annotations as _annotations

from abc import ABC
from contextvars import ContextVar
from itertools import combinations
from typing import Generic, TypeVar, TYPE_CHECKING

from pyrogram.types import Update as PyroUpdate

from ..typings import UpdateType

if TYPE_CHECKING:
    import asyncio
    from collections.abc import Iterator, Sequence
    from concurrent.futures import ThreadPoolExecutor

    from ..dispatcher import Dispatcher


handler_worker_var: ContextVar[tuple[Dispatcher, asyncio.Task[None]] | None] = ContextVar(
    "handler_worker_var", default=None
)
"""The dispatcher and worker task running the current handler, or `None` outside one."""


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

    def __init_subclass__(cls, **kw: object) -> None:
        """Check that a concrete subclass declares a Pyrogram update type.

        Args:
            **kw: Passed on to the next base's `__init_subclass__`.

        Raises:
            TypeError: If `__update_type__` is missing or is not a Pyrogram update class.
        """
        super().__init_subclass__(**kw)

        if ABC not in cls.__bases__:
            _check_update_type(cls)

    def __init__(self, **kw: object) -> None:
        """Check the declared update type again, then pass `kw` on to the next base.

        Args:
            **kw: Passed on to the next base's `__init__`.

        Raises:
            TypeError: If `__update_type__` is missing or is not a Pyrogram update class.
        """
        _check_update_type(self.__class__)
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


def _check_update_type(cls: type) -> None:
    """Check that `cls` declares a Pyrogram update class as `__update_type__`.

    Args:
        cls: The `UpdateBound` subclass to check.

    Raises:
        TypeError: If `__update_type__` is missing or is not a Pyrogram update class.
    """
    update_type = getattr(cls, "__update_type__", None)

    if update_type is None:
        msg = f"{cls.__name__} must define __update_type__"
        raise TypeError(msg)

    if not (isinstance(update_type, type) and issubclass(update_type, PyroUpdate)):
        msg = f"{cls.__name__}.__update_type__ must be a subclass of {PyroUpdate.__name__}"
        raise TypeError(msg)


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


_ItemT = TypeVar("_ItemT")
"""The item type of the sequence `subsets_largest_first` takes apart."""


def subsets_largest_first(items: Sequence[_ItemT]) -> Iterator[tuple[_ItemT, ...]]:
    """Yield every subset of `items`, from all of them down to none.

    Subsets of one size come in the order of `items`, and each keeps that
    order, so the first item outranks the next among equal sizes.

    Args:
        items: The items to combine.

    Returns:
        An iterator over the subsets, each a tuple.

    Example:
        >>> list(subsets_largest_first(["user", "message"]))
        [('user', 'message'), ('user',), ('message',), ()]
    """
    for size in range(len(items), -1, -1):
        yield from combinations(items, size)


__all__ = (
    "handler_worker_var",
    "UpdateBound",
    "get_update_executor",
    "subsets_largest_first",
)
