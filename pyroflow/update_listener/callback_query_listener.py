"""Listener for callback query updates."""

from __future__ import annotations as _annotations

from typing import TYPE_CHECKING

from ..models import ListenerKey
from ..types import CallbackQuery
from .update_listener import UpdateListener


class CallbackQueryListener(UpdateListener[CallbackQuery]):
    """Listener keyed by the chat, user and message a callback query belongs to.

    Example:
        >>> import asyncio
        >>> from pyrogram.types import Chat, Message, User
        >>> async def main():
        ...     listener = CallbackQueryListener()
        ...     waiter = asyncio.create_task(listener.listen(1, 2, 3))
        ...     await asyncio.sleep(0)
        ...     message = Message(id=3, chat=Chat(id=1))
        ...     query = CallbackQuery(
        ...         id="q", from_user=User(id=2), chat_instance="c", message=message
        ...     )
        ...     await listener.resolve(query)
        ...     return (await waiter).id
        >>> asyncio.run(main())
        'q'
    """

    __update_type__ = CallbackQuery
    """The Pyrogram update class this listener waits for."""

    if not TYPE_CHECKING:

        def __init__(self, *args: object, **kw: object) -> None:
            """Initialize the listener, defaulting to the built-in key functions.

            Args:
                *args: Passed to `UpdateListener`.
                **kw: Passed to `UpdateListener`.
            """
            super().__init__(*args, **kw)

            if self.extract_key_func is None:
                self.extract_key_func = self._extract_key

    async def _extract_key(self, update: CallbackQuery) -> ListenerKey | None:
        """Default `extract_key_func`: key the callback by chat, user and message.

        Args:
            update: The incoming callback query.

        Returns:
            The key `(message chat id, sender id, message id)`, or `None` if
            the callback has no message or its message has no chat.
        """
        m = update.message

        if m is None or m.chat is None:
            return None

        return ListenerKey(m.chat.id, update.from_user.id, m.id)  # ty: ignore[invalid-argument-type]  # pyrogram types `Chat.id` as `int | None`; a received chat always has an id


__all__ = ("CallbackQueryListener",)
