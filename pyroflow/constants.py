"""Public constants used by pyroflow."""

from __future__ import annotations as _annotations

from typing import Final

BOT_COMMANDS_ATTR: Final[str] = "_pyroflow_bot_commands"
"""Namespaced `Handler` attribute where `mark_bot_commands` stores its declarations."""


ASK_MESSAGE_ID_META_KEY: Final[str] = "message_id"
"""`meta` key under which `ask` records the id of the message it sent or edited."""


__all__ = ("ASK_MESSAGE_ID_META_KEY", "BOT_COMMANDS_ATTR")
