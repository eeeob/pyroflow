"""Handler history for `CallbackQuery` updates."""

from __future__ import annotations as _annotations

from typing import Any, TYPE_CHECKING

from ..types import CallbackQuery
from .update_history import UpdateHistory


class CallbackQueryHistory(UpdateHistory[CallbackQuery]):
    """Handler history for callback queries, keyed by `(chat_id, user_id, message_id)`.

    The key comes from the query's message; queries without a message in a chat are
    not recorded. The stored data is the callback data.

    Example:
        >>> import asyncio
        >>> from pyrogram.types import CallbackQuery, Chat, Message, User
        >>> history = CallbackQueryHistory()
        >>> query = CallbackQuery(
        ...     id="1",
        ...     from_user=User(id=3),
        ...     chat_instance="0",
        ...     message=Message(id=7, chat=Chat(id=5)),
        ...     data="yes",
        ... )
        >>> asyncio.run(history.extract_key(query)), asyncio.run(history.extract_data(query))
        ((5, 3, 7), 'yes')
    """

    __update_type__ = CallbackQuery
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
        self, update: CallbackQuery
    ) -> tuple[int | None, int | None, int] | None:
        """Return the `(chat_id, user_id, message_id)` key of the query's message.

        `None` when the query has no message in a chat, such as one from an
        inline message.
        """
        message = update.message

        if message is None or message.chat is None:
            return None

        return (message.chat.id, getattr(update.from_user, "id", None), message.id)

    async def _extract_data(self, update: CallbackQuery) -> str | bytes | None:
        """Return the callback data."""
        return update.data


__all__ = ("CallbackQueryHistory",)
