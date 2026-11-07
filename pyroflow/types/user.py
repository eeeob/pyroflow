"""Pyrogram's `User`, patched with `lang_code`, its messages typed as the patched class."""

from __future__ import annotations as _annotations

from typing import TYPE_CHECKING

from pyrogram.types import User as PyroUser

from ..utils import patch_cls

if TYPE_CHECKING:
    from ..client import Client
    from .message import Message


@patch_cls
class User(PyroUser):
    """Pyrogram `User` extended with `lang_code`."""

    _client: Client
    """Client that received this user."""
    pinned_message: Message | None
    """The user's pinned message."""
    personal_channel_message: Message | None
    """Last message in the user's personal channel."""

    @property
    def lang_code(self) -> str | None:
        """Primary language subtag of `language_code`, lowercased, or `None` if unknown.

        Example:
            >>> User(id=1, language_code="pt-BR").lang_code
            'pt'
            >>> User(id=2).lang_code is None
            True
        """
        return lang.split("-")[0].lower() if (lang := self.language_code) else None


__all__ = ("User",)
