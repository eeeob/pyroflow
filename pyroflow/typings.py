from typing import (
    TYPE_CHECKING, Any, Callable, Dict, Optional, Tuple, Type, TypeAlias, Union,
)
from pyrogram.types import BotCommand, BotCommandScope
from .utils.typings import MaybeList, MaybeCoroutineCallable

if TYPE_CHECKING:
    from .types import Message


UpdateCoordinatorKeyT: TypeAlias = Tuple[Union[int, str], ...]
UpdateHistoryKeyT: TypeAlias = UpdateCoordinatorKeyT
ListenerCoordinatorIdT: TypeAlias = Union[str, int]

# One declaration of "which bot commands a handler answers to", as accepted by
# mark_bot_commands(): a command (or list of them) on its own, optionally
# preceded by the scope it applies to, optionally preceded by a language code.
BotCommandEntryT: TypeAlias = Union[
    MaybeList[BotCommand],
    Tuple[BotCommandScope, MaybeList[BotCommand]],
    Tuple[str, BotCommandScope, MaybeList[BotCommand]],
]

# A BotCommandEntryT expanded into its three parts, with whatever the entry
# left out filled in as None ("unrestricted").
BotCommandPartsT: TypeAlias = Tuple[
    Optional[str], Optional[BotCommandScope], MaybeList[BotCommand]
]

# The key a collected command group is filed under by BotCommandsMixin.
BotCommandGroupKeyT: TypeAlias = Tuple[Optional[str], Optional[BotCommandScope]]

# Error handlers for ask() only — nothing else consults this mapping. Maps one
# or more exception types to a handler invoked with (exc, message) when that
# error occurs while ask() awaits the listener, before listening finishes.
# Used by Client.ask(error_handlers=...) and Client.ask_error_handlers.
AskErrorHandlersT: TypeAlias = Dict[
    Union[Type[Exception], Tuple[Type[Exception], ...]],
    MaybeCoroutineCallable[[Exception, "Message"], Any],
]

# Either an explicit message id, or a synchronous callable receiving the
# sent/edited message (m) and returning the id to listen for (or None).
# Must be fast and non-blocking: it is called inline, not via to_thread.
ListenMessageIdT: TypeAlias = Union[int, Callable[["Message"], Optional[int]]]


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
