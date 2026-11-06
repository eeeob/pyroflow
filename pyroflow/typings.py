"""Type aliases shared across pyroflow."""

from __future__ import annotations as _annotations

from typing import (
    TypeVar,
    TypeAlias,
)

from pyrogram.types import BotCommand, BotCommandScope, Update as PyroUpdate
from pytrove.typings import MaybeList

from .enums import EphemeralUpdates, ListenMessageId


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

ListenMessageIdT: TypeAlias = int | ListenMessageId | EphemeralUpdates
"""A message id, a `ListenMessageId` for the message `ask` sent or edited, or `EphemeralUpdates`."""

ListenerMessageIdT: TypeAlias = int | EphemeralUpdates
"""What a listener key holds for a message: its id, or `EphemeralUpdates` for ephemeral updates."""


__all__ = (
    "UpdateType",
    "BotCommandEntryT",
    "BotCommandPartsT",
    "BotCommandGroupKeyT",
    "ListenMessageIdT",
    "ListenerMessageIdT",
)
