"""Handler history for `Message` updates."""

from __future__ import annotations as _annotations

from typing import Any, TYPE_CHECKING

from ..types import Message
from ..utils import get_message_identity
from .update_history import UpdateHistory


class MessageHistory(UpdateHistory[Message]):
    """Handler history for messages, keyed by `(business_connection_id, scheduled, chat_id, message_id, user_id)`.

    The first four come from `get_message_identity`, so business, scheduled and
    ephemeral messages never share a history with regular ones. Edits share
    the message's history. Messages without a chat are not recorded; the
    stored data is the message text.

    Example:
        >>> import asyncio
        >>> from pyrogram.types import Chat
        >>> history = MessageHistory()
        >>> message = Message(id=7, chat=Chat(id=5), text="hi")
        >>> asyncio.run(history.extract_key(message)), asyncio.run(history.extract_data(message))
        (('', 0, 5, 7, None), 'hi')
    """

    __update_type__ = Message
    """Update class whose handlers this history records."""

    if not TYPE_CHECKING:

        def __init__(self, *args: Any, **kw: Any) -> None:
            """Initialise the history, defaulting any callable not passed to this class's own."""
            super().__init__(*args, **kw)

            if self.extract_key_func is None:
                self.extract_key_func = self._extract_key

            if self.extract_data_func is None:
                self.extract_data_func = self._extract_data

    async def _extract_key(
        self, update: Message
    ) -> tuple[str, int, int, int | str, int | None] | None:
        """Return the message's identity followed by `user_id`, or `None` without a chat.

        `user_id` is `None` without a sender.
        """
        if update.chat is None:
            return None

        return (*get_message_identity(update), getattr(update.from_user, "id", None))

    async def _extract_data(self, update: Message) -> str | None:
        """Return the message text."""
        return update.text


__all__ = ("MessageHistory",)
