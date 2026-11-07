"""Listener for message updates."""

from __future__ import annotations as _annotations

from typing import TYPE_CHECKING

from ..models import MessageKey
from ..types import Message
from .update_listener import UpdateListener

if TYPE_CHECKING:
    import sys

    if sys.version_info >= (3, 11):
        from typing import Unpack
    else:
        from typing_extensions import Unpack

    from .update_listener import ListenKw


class MessageListener(UpdateListener[Message, MessageKey]):
    """Listener keyed by the chat, sender and topic of incoming messages.

    Example:
        >>> import asyncio
        >>> from pyrogram.types import Chat, User
        >>> async def main():
        ...     listener = MessageListener()
        ...     await listener.start()
        ...     waiter = asyncio.create_task(listener.listen(chat_id=1, user_id=2))
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

    if not TYPE_CHECKING:

        def __init__(self, *args: object, **kw: object) -> None:
            """Initialize the listener, defaulting to the built-in key function.

            Args:
                *args: Passed to `UpdateListener`.
                **kw: Passed to `UpdateListener`.
            """
            super().__init__(*args, **kw)

            if self.extract_key_func is None:
                self.extract_key_func = self._extract_key

    async def listen(  # ty: ignore[invalid-method-override]  # takes the key fields; `UpdateListener.listen` takes the whole key
        self,
        chat_id: int | None = None,
        user_id: int | None = None,
        message_thread_id: int | None = None,
        direct_messages_topic_id: int | None = None,
        ephemeral: bool = False,
        **kw: Unpack[ListenKw],
    ) -> Message:
        """Wait for the next message matching the given fields; `None` matches any value.

        Also callable as `listener(...)`. See `UpdateListener.listen` for the
        arguments of the wait and the errors.

        Args:
            chat_id: The chat to listen in; a user's private chat has the
                user's id.
            user_id: The sender to wait for.
            message_thread_id: The forum topic to listen in.
            direct_messages_topic_id: The topic of a channel's direct messages
                chat to listen in.
            ephemeral: Wait on ephemeral messages, the only wait they reach.
            **kw: The arguments of the wait, as `UpdateListener.listen` takes them.

        Returns:
            The matching message.
        """
        return await super().listen(
            self.__key_type__(
                chat_id=chat_id,
                user_id=user_id,
                message_thread_id=message_thread_id,
                direct_messages_topic_id=direct_messages_topic_id,
                ephemeral=ephemeral,
            ),
            **kw,
        )

    __call__ = listen  # ty: ignore[invalid-method-override]  # takes the key fields; `UpdateListener.listen` takes the whole key
    """Alias of `listen`, so the listener can be awaited as `listener(...)`."""

    def _extract_key(self, update: Message) -> MessageKey | None:
        """Default `extract_key_func`: key the message with `MessageKey.from_message`.

        Args:
            update: The incoming message.

        Returns:
            The key of the message, or `None` for outgoing, service, empty or
            edited messages, messages sent by this account, and messages
            without a chat.
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

        return self.__key_type__.from_message(update)


__all__ = ("MessageListener",)
