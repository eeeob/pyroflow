"""Type aliases shared across pyroflow."""

from __future__ import annotations as _annotations

from collections.abc import Callable, Hashable
from typing import (
    TypeVar,
    Any,
    TypeAlias,
    TYPE_CHECKING,
)

from pyrogram.types import BotCommand, BotCommandScope, Update as PyroUpdate
from pytrove.typings import MaybeList, MaybeCoroutineCallable

if TYPE_CHECKING:
    from .types import Message


UpdateType = TypeVar("UpdateType", bound=PyroUpdate)
"""The Pyrogram update class a generic listener is bound to."""

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


MetaT: TypeAlias = dict[Hashable, Any]
"""Metadata attached to a listener; `ask` adds the message it sent under `ASK_MESSAGE_ID_META_KEY`."""


__all__ = (
    "UpdateType",
    "BotCommandEntryT",
    "BotCommandPartsT",
    "BotCommandGroupKeyT",
    "AskErrorHandlersT",
    "ListenMessageIdT",
    "MetaT",
)
