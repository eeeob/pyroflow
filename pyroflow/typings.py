"""Type aliases shared across pyroflow."""

from __future__ import annotations as _annotations

from typing import (
    TYPE_CHECKING,
    TypeVar,
    TypeAlias,
)

from pyrogram.types import BotCommand, BotCommandScope, Update as PyroUpdate
from pytrove.typings import MaybeList

if TYPE_CHECKING:
    from .models import ListenerKey


UpdateType = TypeVar("UpdateType", bound=PyroUpdate)
"""The Pyrogram update class a generic listener is bound to."""

# A forward reference: `pyroflow.models` imports this module, so it cannot be imported back here.
KeyT = TypeVar("KeyT", bound="ListenerKey")
"""The `ListenerKey` class a generic listener or listener model is keyed by."""

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


__all__ = (
    "UpdateType",
    "KeyT",
    "BotCommandEntryT",
    "BotCommandPartsT",
    "BotCommandGroupKeyT",
)
