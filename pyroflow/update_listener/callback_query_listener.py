"""Listener for callback query updates."""

from __future__ import annotations as _annotations

from ..models import CallbackQueryKey
from ..types import CallbackQuery
from .update_listener import UpdateListener


class CallbackQueryListener(UpdateListener[CallbackQuery]):
    """Listener keyed by the chat, user and message a callback query belongs to.

    Example:
        >>> import asyncio
        >>> from pyrogram.types import Chat, Message, User
        >>> from pyroflow import Client
        >>> async def main():
        ...     listener = CallbackQueryListener()
        ...     client = Client("doc", api_id=1, api_hash="x", in_memory=True)
        ...     client.register_listener(listener)
        ...     waiter = asyncio.create_task(listener.listen(CallbackQueryKey(1, 2, 3)))
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
    __key_type__ = CallbackQueryKey
    """The key class of the waits of this listener."""


__all__ = ("CallbackQueryListener",)
