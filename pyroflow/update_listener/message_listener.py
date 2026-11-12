"""Listener for message updates."""

from __future__ import annotations as _annotations

from ..models import MessageKey
from ..types import Message
from .update_listener import UpdateListener


class MessageListener(UpdateListener[Message]):
    """Listener keyed by the chat, sender and topic of incoming messages.

    Example:
        >>> import asyncio
        >>> from pyrogram.types import Chat, User
        >>> from pyroflow import Client
        >>> async def main():
        ...     listener = MessageListener()
        ...     client = Client("doc", api_id=1, api_hash="x", in_memory=True)
        ...     client.register_listener(listener)
        ...     await listener.start()
        ...     waiter = asyncio.create_task(listener.listen(MessageKey(1, 2)))
        ...     await asyncio.sleep(0)
        ...     await listener.resolve(Message(id=5, chat=Chat(id=1), from_user=User(id=2)))
        ...     answer = await waiter
        ...     await listener.stop()
        ...     return answer.id
        >>> asyncio.run(main())
        5
    """

    __update_type__ = Message
    """The Pyrogram update class this listener waits for."""
    __key_type__ = MessageKey
    """The key class of the waits of this listener."""


__all__ = ("MessageListener",)
