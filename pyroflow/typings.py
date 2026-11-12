"""Type aliases shared across pyroflow."""

from __future__ import annotations as _annotations

from collections.abc import Hashable
from typing import (
    TypeVar,
    TypeAlias,
)

from pyrogram.types import BotCommand, BotCommandScope, Update as PyroUpdate
from pytrove.typings import MaybeList


UpdateType = TypeVar("UpdateType", bound=PyroUpdate)
"""The Pyrogram update class a generic listener is bound to."""

QuestionT = TypeVar("QuestionT")
"""The question an `AskAgain` asks next: a `str` or an `InputRichMessage`."""

ResultT = TypeVar("ResultT")
"""What the `parse` of an `ask_*_until` method returns to the caller."""

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


CoordinationKeyT: TypeAlias = Hashable
"""What a `CoordinatedDispatcher` groups updates by: any hashable value."""


__all__ = (
    "UpdateType",
    "QuestionT",
    "ResultT",
    "BotCommandEntryT",
    "BotCommandPartsT",
    "BotCommandGroupKeyT",
    "CoordinationKeyT",
)
