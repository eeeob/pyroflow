"""Listener for message updates."""

from __future__ import annotations as _annotations

from typing import TYPE_CHECKING

from ..models import ListenerKey
from ..types import Message
from .update_listener import UpdateListener


class MessageListener(UpdateListener[Message]):
    """Listener keyed by the chat, sender and id of incoming messages.

    Example:
        >>> import asyncio
        >>> from pyrogram.types import Chat, User
        >>> async def main():
        ...     listener = MessageListener()
        ...     await listener.start()
        ...     waiter = asyncio.create_task(listener.listen(1, 2))
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
    _message_id_names_one_update = True
    """A key's `message_id` is the incoming message's own id, so it names a single update."""

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

    async def _extract_key(self, update: Message) -> ListenerKey | None:
        """Default `extract_key_func`: key the message by chat, sender and id.

        Args:
            update: The incoming message.

        Returns:
            The key `(chat id, sender id or None, message id)`, or `None` for
            outgoing, service, empty or edited messages, messages sent by this
            account, and messages without a chat.
        """
        if (
            update.outgoing
            or update.service
            or getattr(update.from_user, "is_self", False)
            or update.empty
            or update.edit_date
            or update.edit_hidden
            or update.chat is None
        ):
            return None

        # `from_user` قد يكون `None` (مشرف مجهول، منشور قناة)
        return ListenerKey(
            update.chat.id,  # ty: ignore[invalid-argument-type]  # pyrogram types `Chat.id` as `int | None`; a received chat always has an id
            getattr(update.from_user, "id", None),
            update.id,
        )


__all__ = ("MessageListener",)
