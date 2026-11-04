"""Listener for message updates."""

from __future__ import annotations as _annotations

import logging
from typing import TYPE_CHECKING

from ..models import ListenerKey
from ..types import Message
from .update_listener import UpdateListener

if TYPE_CHECKING:
    from pyrogram.filters import Filter


log = logging.getLogger(__name__)


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

    if not TYPE_CHECKING:

        def __init__(self, *args: object, **kw: object) -> None:
            """Initialize the listener, defaulting to the built-in key and listen functions.

            Args:
                *args: Passed to `UpdateListener`.
                **kw: Passed to `UpdateListener`.
            """
            super().__init__(*args, **kw)

            if self.extract_key_func is None:
                self.extract_key_func = self._extract_key

            if self.on_listen_func is None:
                self.on_listen_func = self._warn_single_update_filter

    def _warn_single_update_filter(
        self,
        *,
        chat_id: int,
        user_id: int | None,
        message_id: int | None,
        filters: Filter | None,
        strict: bool,
        **kw: object,
    ) -> None:
        """Default `on_listen_func`: warn of a wait a rejected message would leave open.

        A key's `message_id` is the incoming message's own id, so it names a
        single message; if a non-strict filter rejects it, no other message
        can match and the wait stays open until its timeout.

        Args:
            chat_id: As in `listen`.
            user_id: As in `listen`.
            message_id: As in `listen`.
            filters: As in `listen`.
            strict: As in `listen`.
            **kw: The other `listen` arguments, unused.
        """
        if message_id is not None and filters is not None and not strict:
            log.warning(
                "Listener for %s waits for a single update with a non-strict filter; "
                "if the filter rejects it, the wait stays open until its timeout",
                ListenerKey(chat_id, user_id, message_id),
            )

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
