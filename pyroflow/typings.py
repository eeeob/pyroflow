"""Type aliases shared across pyroflow."""

from __future__ import annotations as _annotations

from collections.abc import Hashable
from typing import (
    TypeVar,
    TypeAlias,
)

from pyrogram.types import BotCommand, BotCommandScope, Update as PyroUpdate
from pytrove.typings import MaybeAwaitableCallable as _MaybeAwaitableCallable, MaybeList


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


MaybeAwaitableCallable: TypeAlias = _MaybeAwaitableCallable
"""A sync callable, or one whose result is awaited; pytrove's `MaybeAwaitableCallable` itself.

Warning:
    It is called on the event loop itself, sync or not, never in a thread. A
    sync function that is slow or blocks, on I/O or heavy work, stops every
    update until it returns. Keep it light; for heavy work, pass an
    `async def` that awaits `asyncio.to_thread`.
"""


__all__ = (
    "UpdateType",
    "QuestionT",
    "ResultT",
    "BotCommandEntryT",
    "BotCommandPartsT",
    "BotCommandGroupKeyT",
    "CoordinationKeyT",
    "MaybeAwaitableCallable",
)
