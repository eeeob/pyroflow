"""Type aliases shared across pyroflow."""

from __future__ import annotations as _annotations

from collections.abc import Callable
from typing import (
    Protocol,
    TypeVar,
    Any,
    Literal,
    TypeAlias,
    TYPE_CHECKING,
)

from pyrogram.types import BotCommand, BotCommandScope, Update as PyroUpdate
from pytrove.typings import MaybeList, MaybeCoroutineCallable

from .models import ListenerKey

if TYPE_CHECKING:
    from types import TracebackType

    from .types import Message


# The Pyrogram update class a generic listener, coordinated policy or history
# is bound to.
UpdateType = TypeVar("UpdateType", bound=PyroUpdate)

UpdateCoordinatorKeyT: TypeAlias = tuple[int | str, ...]
UpdateHistoryKeyT: TypeAlias = UpdateCoordinatorKeyT
ListenerCoordinatorIdT: TypeAlias = str | int

# The key a listener coordinator locks on.
LockKeyT: TypeAlias = (
    int | tuple[int] | tuple[int, int | None] | tuple[int, int | None, int | None] | ListenerKey
)

# The key namespaces an `UpdateCoordinator` keeps apart: the update lock and the
# handled registry.
UpdateCoordinatorSectionT: TypeAlias = Literal["lock", "handled"]

# One declaration of "which bot commands a handler answers to", as accepted by
# `mark_bot_commands()`: a command (or list of them) on its own, optionally
# preceded by the scope it applies to, optionally preceded by a language code.
BotCommandEntryT: TypeAlias = (
    MaybeList[BotCommand]
    | tuple[BotCommandScope, MaybeList[BotCommand]]
    | tuple[str, BotCommandScope, MaybeList[BotCommand]]
)

# A `BotCommandEntryT` expanded into its three parts, with whatever the entry
# left out filled in as `None` ("unrestricted").
BotCommandPartsT: TypeAlias = tuple[str | None, BotCommandScope | None, MaybeList[BotCommand]]

# The key a collected command group is filed under by `BotCommandsMixin`.
BotCommandGroupKeyT: TypeAlias = tuple[str | None, BotCommandScope | None]

# Error handlers consulted only by `ask()`: maps one or more exception types to
# a handler called with `(exc, message)` when that error occurs while `ask()`
# awaits the listener. Used by `Client.ask(error_handlers=...)` and
# `Client.ask_error_handlers`.
AskErrorHandlersT: TypeAlias = dict[
    type[Exception] | tuple[type[Exception], ...],
    MaybeCoroutineCallable[[Exception, "Message"], Any],
]

# Either an explicit message id, or a synchronous callable receiving the
# sent/edited message (`m`) and returning the id to listen for (or `None`).
# Must be fast and non-blocking: it is called inline, not via `to_thread`.
ListenMessageIdT: TypeAlias = int | Callable[["Message"], int | None]


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
    "UpdateCoordinatorKeyT",
    "UpdateCoordinatorSectionT",
    "UpdateHistoryKeyT",
    "ListenerCoordinatorIdT",
    "LockKeyT",
    "BotCommandEntryT",
    "BotCommandPartsT",
    "BotCommandGroupKeyT",
    "AskErrorHandlersT",
    "ListenMessageIdT",
)
