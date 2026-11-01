"""Internal bot command helpers: the `mark_bot_commands` decorator and command entry expansion."""

from __future__ import annotations as _annotations

from typing import Final, TYPE_CHECKING

from pyrogram import handlers
from pyrogram.types import BotCommand

from ..constants import BOT_COMMANDS_ATTR

if TYPE_CHECKING:
    from collections.abc import Callable

    from pyrogram.handlers import Handler
    from pytrove.typings import _FT

    from ..typings import BotCommandEntryT, BotCommandPartsT

_MESSAGES_HANDLER: Final[tuple[type[Handler], ...]] = tuple(
    getattr(handlers, name)
    for name in ("MessageHandler", "BusinessMessageHandler")
    if hasattr(handlers, name)
)
"""Handler types `mark_bot_commands` marks; `BusinessMessageHandler` only where the installed Pyrogram has it."""


def mark_bot_commands(*entries: BotCommandEntryT) -> Callable[[_FT], _FT]:
    """Mark a handler function with the bot commands it answers to.

    Nothing is sent here: `entries` are stored under `BOT_COMMANDS_ATTR` on each
    `MessageHandler` and `BusinessMessageHandler` in `func.handlers`, other
    handlers are left untouched, and `BotCommandsMixin.push_bot_commands`
    publishes them when the client starts.

    Apply it above an unbound `@Client.on_message(...)`, which creates
    `func.handlers`. The bound form `@app.on_message(...)` sets nothing, so
    there is nothing to mark.

    Args:
        *entries: The command declarations, each a `BotCommandEntryT`.

    Returns:
        A decorator that stores `entries` on the function's message handlers
        and returns the function unchanged.

    Example:
        >>> from pyrogram import Client as PyroClient, filters
        >>> from pyrogram.types import BotCommand
        >>> @mark_bot_commands(BotCommand("start", "Start the bot"))
        ... @PyroClient.on_message(filters.command("start"))
        ... async def on_start(client, message):
        ...     await message.reply("Hi!")
        >>> [c.command for h, _ in on_start.handlers for c in getattr(h, BOT_COMMANDS_ATTR)]
        ['start']
    """

    def decorator(func: _FT) -> _FT:
        """Store `entries` on each message handler in `func.handlers`."""
        for handler, _ in getattr(func, "handlers", []):
            if not isinstance(handler, _MESSAGES_HANDLER):
                continue
            setattr(handler, BOT_COMMANDS_ATTR, entries)
        return func

    return decorator


def split_bot_command_entry(entry: BotCommandEntryT) -> BotCommandPartsT:
    """Expand any `BotCommandEntryT` shape into its `(language_code, scope, commands)` parts.

    The parts the entry left out are filled with `None`.

    Args:
        entry: Commands alone, a `(scope, commands)` pair, or a
            `(language_code, scope, commands)` triple.

    Returns:
        The `(language_code, scope, commands)` triple.

    Example:
        >>> from pyrogram.types import BotCommandScopeDefault
        >>> split_bot_command_entry([])
        (None, None, [])
        >>> split_bot_command_entry((BotCommandScopeDefault(), []))
        (None, pyrogram.types.BotCommandScopeDefault(type='default'), [])
        >>> split_bot_command_entry(("en", BotCommandScopeDefault(), []))
        ('en', pyrogram.types.BotCommandScopeDefault(type='default'), [])
    """
    if isinstance(entry, (BotCommand, list)):
        return None, None, entry
    if len(entry) == 2:
        return None, *entry
    return entry


__all__ = (
    "mark_bot_commands",
    "split_bot_command_entry",
)
