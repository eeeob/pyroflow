"""Coordination policy for `Message` updates."""

from __future__ import annotations as _annotations

from typing import Any, TYPE_CHECKING

from ..types import Message
from .update_coordinated import UpdateCoordinated

if TYPE_CHECKING:
    from ..typings import CoordinatedUpdateKeyT, CoordinatedUpdateIdT


class MessageCoordinated(UpdateCoordinated[Message]):
    """Coordinates messages, locked per chat and identified per message edit by default.

    Example:
        >>> import asyncio
        >>> from pyrogram.types import Chat
        >>> message = Message(id=42, chat=Chat(id=-1000000000123))
        >>> coordinated = MessageCoordinated()
        >>> asyncio.run(coordinated.extract_key(message)), asyncio.run(coordinated.extract_update_id(message))
        ((-1000000000123,), (-1000000000123, 42, 0))
    """

    __update_type__ = Message
    """Update class this policy coordinates."""

    if not TYPE_CHECKING:

        def __init__(self, *args: Any, **kw: Any) -> None:
            """Initialise the policy, defaulting any callable not passed to this class's own."""
            super().__init__(*args, **kw)

            if self.extract_key_func is None:
                self.extract_key_func = self._extract_key

            if self.extract_update_id_func is None:
                self.extract_update_id_func = self._extract_update_id

    async def _extract_key(self, update: Message) -> CoordinatedUpdateKeyT | None:
        """Lock per chat, so a chat's messages are coordinated one at a time.

        A message without a chat is left uncoordinated. Pass `extract_key_func`
        to pick another level, such as `lambda m: (m.chat.id, m.id)` for one
        message.
        """
        return (update.chat.id,) if update.chat else None  # ty: ignore[invalid-return-type]  # `pyrogram` types `Chat.id` as `Optional`; a parsed chat always carries it

    async def _extract_update_id(self, update: Message) -> CoordinatedUpdateIdT:
        """Identify the message by its chat id, its id and its edit time.

        An edit keeps the message id, so the edit time (`0` before any edit)
        tells an edit apart from the original and from other edits.
        """
        edited = int(update.edit_date.timestamp()) if update.edit_date else 0
        return (update.chat.id, update.id, edited)  # ty: ignore[invalid-return-type]  # `pyrogram` types `Chat.id` as `Optional`; a parsed chat always carries it  # ty: ignore[unresolved-attribute]  # `pyrogram` types `Message.raw` as `Optional`; dispatched messages always carry it


__all__ = ("MessageCoordinated",)
