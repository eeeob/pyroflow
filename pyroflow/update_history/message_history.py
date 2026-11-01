"""Handler history for :class:`Message` updates."""

from __future__ import annotations as _annotations

from typing import Any, cast, TYPE_CHECKING

from ..types import Message
from .update_history import UpdateHistory

if TYPE_CHECKING:
    from pyrogram.types import Chat


class MessageHistory(UpdateHistory[Message]):
    """Handler history for messages, keyed by ``(chat_id, user_id, message_id)``.

    Messages without a chat are not recorded; the stored data is the message text.
    """

    __update_type__ = Message

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

    async def _is_recordable(self, update: Message) -> bool:
        """Return whether the message belongs to a chat."""
        return update.chat is not None

    async def _extract_key(self, update: Message) -> tuple[int | None, int | None, int]:
        """Return the ``(chat_id, user_id, message_id)`` key; ``user_id`` is ``None`` without a sender."""
        # `is_recordable()` guarantees the chat exists.
        return (
            cast("Chat", update.chat).id,
            getattr(update.from_user, "id", None),
            update.id,
        )

    async def _extract_data(self, update: Message) -> str | None:
        """Return the message text."""
        return update.text


__all__ = ("MessageHistory",)
