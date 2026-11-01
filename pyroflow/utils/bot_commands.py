"""Internal bot command helpers: expanding a command declaration into its parts."""

from __future__ import annotations as _annotations
from typing import TYPE_CHECKING

from pyrogram.types import BotCommand

# Public in pyroflow.bot_commands; re-exported so pyroflow.utils keeps offering it.
from ..bot_commands import mark_bot_commands

if TYPE_CHECKING:
    from ..typings import BotCommandEntryT, BotCommandPartsT


def split_bot_command_entry(entry: BotCommandEntryT) -> BotCommandPartsT:
    """Expand any :data:`BotCommandEntryT` shape into its ``(language_code, scope, commands)`` parts.

    The parts the entry left out are filled with ``None``.
    """
    if isinstance(entry, (BotCommand, list)):
        return None, None, entry
    if len(entry) == 2:
        return None, *entry
    return entry


__all__ = (
    "split_bot_command_entry",
    "mark_bot_commands",
)
