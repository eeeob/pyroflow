"""Coordination policy for `CallbackQuery` updates."""

from __future__ import annotations as _annotations

from typing import Any, TYPE_CHECKING

from ..types import CallbackQuery
from .update_coordinated import UpdateCoordinated

if TYPE_CHECKING:
    from ..typings import UpdateCoordinatorKeyT


class CallbackQueryCoordinated(UpdateCoordinated[CallbackQuery]):
    """Coordinates callback queries, locked per chat and identified per query by default.

    Example:
        >>> import asyncio
        >>> from pyrogram.types import Chat
        >>> from pyroflow.types import Message, User
        >>> query = CallbackQuery(id="q1", from_user=User(id=7), message=Message(id=1, chat=Chat(id=-100)))
        >>> asyncio.run(CallbackQueryCoordinated().extract_key(query))
        (-100,)
    """

    __update_type__ = CallbackQuery
    """Update class this policy coordinates."""

    if not TYPE_CHECKING:

        def __init__(self, *args: Any, **kw: Any) -> None:
            """Initialise the policy, defaulting any callable not passed to this class's own."""
            super().__init__(*args, **kw)

            if self.extract_key_func is None:
                self.extract_key_func = self._extract_key

            if self.extract_update_id_func is None:
                self.extract_update_id_func = self._extract_update_id

    async def _extract_key(self, update: CallbackQuery) -> UpdateCoordinatorKeyT:
        """Lock per chat of the query's message, or per query when it has none.

        A query from an inline message carries no chat, so it is locked on its
        own id to stay coordinated. Pass `extract_key_func` to pick another
        level.
        """
        chat = update.message.chat if update.message is not None else None

        if chat is not None and chat.id is not None:
            return (chat.id,)

        return (update.id,)

    async def _extract_update_id(self, update: CallbackQuery) -> UpdateCoordinatorKeyT:
        """Identify the query by its id."""
        return (update.id,)


__all__ = ("CallbackQueryCoordinated",)
