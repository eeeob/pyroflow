"""Callback query listener that cancels the message listen waiting on the pressed message."""

from __future__ import annotations as _annotations

from typing import TYPE_CHECKING

from ..constants import ASK_MESSAGE_ID_META_KEY
from ..models import ListenerKey
from ..types import Message
from .callback_query_listener import CallbackQueryListener

if TYPE_CHECKING:
    from collections.abc import Hashable

    from ..types import CallbackQuery


class MessageListenCancellingCallbackQueryListener(CallbackQueryListener):
    """`CallbackQueryListener` whose untaken presses cancel the message listen tied to the pressed message.

    When no callback wait takes a press, the client's message listener
    (`Client.message_listen`) is searched for a wait tied to the pressed
    message: its `meta[message_id_meta_key]` is that message's id, as `ask`
    records it. That wait ends with `ListenerCancelled`. Only message waits
    are cancelled, and only those aimed at the presser or at anyone in the
    chat. A press that a callback wait takes cancels nothing.

    For example, a question sent with `ask` can carry a "back" button: a
    press on it ends the wait for the text answer.

    Example:
        >>> import asyncio
        >>> from types import SimpleNamespace
        >>> from pyrogram.types import CallbackQuery, Chat, User
        >>> from pyroflow.errors import ListenerCancelled
        >>> from pyroflow.update_listener import MessageListener
        >>> async def main():
        ...     messages = MessageListener()
        ...     waiter = asyncio.create_task(messages.listen(1, 2, meta={"message_id": 3}))
        ...     await asyncio.sleep(0)
        ...     query = CallbackQuery(
        ...         id="q",
        ...         from_user=User(id=2),
        ...         chat_instance="c",
        ...         message=Message(id=3, chat=Chat(id=1)),
        ...     )
        ...     query._client = SimpleNamespace(listeners={Message: messages})
        ...     await MessageListenCancellingCallbackQueryListener().resolve(query)
        ...     try:
        ...         await waiter
        ...     except ListenerCancelled:
        ...         return "cancelled"
        >>> asyncio.run(main())
        'cancelled'
    """

    message_id_meta_key: Hashable = ASK_MESSAGE_ID_META_KEY
    """`meta` key holding the id of the message a message wait is tied to; set it on a subclass or an instance.

    `ask` writes the id under `ASK_MESSAGE_ID_META_KEY`, so change this only for
    waits whose `meta` carries the id under another key.
    """

    async def resolve(self, update: CallbackQuery) -> bool:
        """Resolve the callback; when no callback listener takes it, cancel the message listen on its message.

        Args:
            update: The incoming callback query.

        Returns:
            Whether a callback listener took the update.
        """
        resolved = await super().resolve(update)

        if not resolved:
            self._cancel_message_listen(update)

        return resolved

    def _cancel_message_listen(self, update: CallbackQuery) -> None:
        """Cancel the message listen tied to the pressed message.

        The candidates are the sub-keys of `(chat, presser, pressed message)`,
        so a press only ends a wait aimed at the presser or at anyone in the
        chat; the first whose `meta[message_id_meta_key]` is the pressed
        message's id is cancelled. Nothing is cancelled when the callback
        carries no message, chat or message id, or the client has no message
        listener.

        Args:
            update: The incoming callback query.
        """
        m = update.message

        if m is None or m.chat is None or not getattr(m, "id", None):
            return

        m_listen = update._client.listeners.get(Message)

        if m_listen is None:
            return

        for sub in ListenerKey(m.chat.id, update.from_user.id, m.id).sub_keys():  # ty: ignore[invalid-argument-type]  # pyrogram types `Chat.id` as `int | None`; a received chat always has an id
            listener = m_listen.listeners.get(sub)

            if listener is not None and (listener.meta or {}).get(self.message_id_meta_key) == m.id:
                m_listen.cancel(sub)
                return


__all__ = ("MessageListenCancellingCallbackQueryListener",)
