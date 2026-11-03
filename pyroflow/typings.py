"""Type aliases shared across pyroflow."""

from __future__ import annotations as _annotations

from collections.abc import Callable
from typing import (
    Protocol,
    TypeVar,
    Any,
    TypeAlias,
    TYPE_CHECKING,
)

from pyrogram.types import BotCommand, BotCommandScope, Update as PyroUpdate
from pytrove.typings import MaybeList, MaybeCoroutineCallable, StrInt

if TYPE_CHECKING:
    from types import TracebackType

    from .types import Message


UpdateType = TypeVar("UpdateType", bound=PyroUpdate)
"""The Pyrogram update class a generic listener or coordinated policy is bound to."""

CoordinatedUpdateKeyT: TypeAlias = tuple[StrInt, ...]
"""An update's lock key, as extracted by a coordinated policy."""
CoordinatedUpdateIdT: TypeAlias = tuple[StrInt, ...]
"""An update's unique identity, used to mark it as handled."""

ListenerCoordinatorIdT: TypeAlias = StrInt
"""Ownership token a listener coordinator hands out at registration time."""

BotCommandEntryT: TypeAlias = (
    MaybeList[BotCommand]
    | tuple[BotCommandScope, MaybeList[BotCommand]]
    | tuple[str, BotCommandScope, MaybeList[BotCommand]]
)
"""A `mark_bot_commands()` declaration: commands, optionally preceded by a scope and language."""

BotCommandPartsT: TypeAlias = tuple[str | None, BotCommandScope | None, MaybeList[BotCommand]]
"""A `BotCommandEntryT` split into language, scope and commands, with `None` for omitted parts."""

BotCommandGroupKeyT: TypeAlias = tuple[str | None, BotCommandScope | None]
"""The key a collected command group is filed under by `BotCommandsMixin`."""

AskErrorHandlersT: TypeAlias = dict[
    type[Exception] | tuple[type[Exception], ...],
    MaybeCoroutineCallable[[Exception, "Message"], Any],
]
"""Handlers called as `(exc, message)` when a mapped error occurs while `ask()` awaits."""

ListenMessageIdT: TypeAlias = int | Callable[["Message"], int | None]
"""A message id, or a fast synchronous callable mapping the sent or edited message to one (or `None`)."""


class AsyncLockProto(Protocol):
    """An asyncio-style lock whose `release` is awaitable too."""

    async def acquire(self) -> bool:
        """Try to acquire the lock.

        Returns:
            `True` once the lock is held, or `False` if a bounded wait
            timed out.
        """

    async def release(self) -> None:
        """Release the lock."""

    async def __aenter__(self) -> object:
        """Acquire the lock on entering the `async with` block."""

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
        /,
    ) -> None:
        """Release the lock on leaving the `async with` block."""


__all__ = (
    "UpdateType",
    "AsyncLockProto",
    "CoordinatedUpdateKeyT",
    "CoordinatedUpdateIdT",
    "ListenerCoordinatorIdT",
    "BotCommandEntryT",
    "BotCommandPartsT",
    "BotCommandGroupKeyT",
    "AskErrorHandlersT",
    "ListenMessageIdT",
)
