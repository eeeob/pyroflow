from __future__ import annotations as _annotations
from typing import (
    TYPE_CHECKING, Any, TypeAlias,
)
from collections.abc import Callable
from pyrogram.types import BotCommand, BotCommandScope
from pytrove.typings import MaybeList, MaybeCoroutineCallable

if TYPE_CHECKING:
    from .types import Message


UpdateCoordinatorKeyT: TypeAlias = tuple[int | str, ...]
UpdateHistoryKeyT: TypeAlias = UpdateCoordinatorKeyT
ListenerCoordinatorIdT: TypeAlias = str | int

# One declaration of "which bot commands a handler answers to", as accepted by
# mark_bot_commands(): a command (or list of them) on its own, optionally
# preceded by the scope it applies to, optionally preceded by a language code.
BotCommandEntryT: TypeAlias = MaybeList[BotCommand] | tuple[BotCommandScope, MaybeList[BotCommand]] | tuple[str, BotCommandScope, MaybeList[BotCommand]]

# A BotCommandEntryT expanded into its three parts, with whatever the entry
# left out filled in as None ("unrestricted").
BotCommandPartsT: TypeAlias = tuple[
    str | None, BotCommandScope | None, MaybeList[BotCommand]
]

# The key a collected command group is filed under by BotCommandsMixin.
BotCommandGroupKeyT: TypeAlias = tuple[str | None, BotCommandScope | None]

# Error handlers for ask() only — nothing else consults this mapping. Maps one
# or more exception types to a handler invoked with (exc, message) when that
# error occurs while ask() awaits the listener, before listening finishes.
# Used by Client.ask(error_handlers=...) and Client.ask_error_handlers.
AskErrorHandlersT: TypeAlias = dict[
    type[Exception] | tuple[type[Exception], ...],
    MaybeCoroutineCallable[[Exception, "Message"], Any],
]

# Either an explicit message id, or a synchronous callable receiving the
# sent/edited message (m) and returning the id to listen for (or None).
# Must be fast and non-blocking: it is called inline, not via to_thread.
ListenMessageIdT: TypeAlias = int | Callable[["Message"], int | None]


__all__ = (
    "UpdateCoordinatorKeyT",
    "UpdateHistoryKeyT",
    "ListenerCoordinatorIdT",
    "BotCommandEntryT",
    "BotCommandPartsT",
    "BotCommandGroupKeyT",
    "AskErrorHandlersT",
    "ListenMessageIdT",
)
