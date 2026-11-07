"""Pyrogram's `CallbackQuery`, with `message` and `from_user` typed as the patched classes."""

from __future__ import annotations as _annotations

from typing import TYPE_CHECKING

from pyrogram.types import CallbackQuery as PyroCallbackQuery

from ..utils import patch_cls

if TYPE_CHECKING:
    from ..client import Client
    from .message import Message
    from .user import User


@patch_cls
class CallbackQuery(PyroCallbackQuery):
    """Pyrogram `CallbackQuery` with `message` and `from_user` typed as the patched classes."""

    _client: Client
    """Client that received this callback query."""
    message: Message | None
    """Message with the pressed button, or `None` for a button on an inline-mode message."""
    from_user: User
    """User who pressed the button."""


__all__ = ("CallbackQuery",)
