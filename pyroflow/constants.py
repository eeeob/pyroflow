"""Public constants used by pyroflow."""

from __future__ import annotations as _annotations

from typing import Final

BOT_COMMANDS_ATTR: Final[str] = "_pyroflow_bot_commands"
"""Namespaced `Handler` attribute where `mark_bot_commands` stores its declarations."""


__all__ = ("BOT_COMMANDS_ATTR",)
