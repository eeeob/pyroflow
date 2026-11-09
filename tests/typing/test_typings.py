"""Static type tests for `pyroflow.typings`."""

from __future__ import annotations as _annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pyrogram.types import BotCommand

    from pyroflow.typings import BotCommandEntryT

    def _check_bot_command_entry(command: BotCommand) -> None:
        entry: BotCommandEntryT = command
        _ = entry
