"""Handler history for `CallbackQuery` updates."""

from __future__ import annotations as _annotations

from typing import Any, cast, TYPE_CHECKING

from ..types import CallbackQuery
from .update_history import UpdateHistory

if TYPE_CHECKING:
    from pyrogram.types import Chat, Message


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
        >>> async def main():
        ...     await history.record(query, "menu")
        ...     return [(r.handler, r.data) for r in await history.get((5, 3, 7))]
        >>> asyncio.run(main())
        [('menu', 'yes')]
    """

    __update_type__ = CallbackQuery

    if not TYPE_CHECKING:

        def __init__(self, *args: Any, **kw: Any) -> None:
            """Initialise the history, defaulting any unset callable to the built-in one."""
            super().__init__(*args, **kw)

            if self.is_recordable_func is None:
                self.is_recordable_func = self._is_recordable

            if self.extract_key_func is None:
                self.extract_key_func = self._extract_key

            if self.extract_data_func is None:
                self.extract_data_func = self._extract_data

    async def _is_recordable(self, update: CallbackQuery) -> bool:
        """Return whether the query has a message that belongs to a chat."""
        m = update.message

        return m is not None and m.chat is not None

    async def _extract_key(self, update: CallbackQuery) -> tuple[int | None, int | None, int]:
        """Return the `(chat_id, user_id, message_id)` key of the query's message."""
        # `is_recordable()` guarantees the message and its chat exist.
        m = cast("Message", update.message)
        chat = cast("Chat", m.chat)

        return (chat.id, getattr(update.from_user, "id", None), m.id)

    async def _extract_data(self, update: CallbackQuery) -> str | bytes | None:
        """Return the callback data."""
        return update.data


__all__ = ("CallbackQueryHistory",)
