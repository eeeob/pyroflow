"""Callback query listener that cancels the message listen waiting on the pressed message."""

from __future__ import annotations as _annotations

from typing import Any, TYPE_CHECKING

from ..enums import MessageListenCancelPolicy
from ..models import ListenerKey
from ..types import Message
from .callback_query_listener import CallbackQueryListener

if TYPE_CHECKING:
    from ..types import CallbackQuery


class MessageListenCancellingCallbackQueryListener(CallbackQueryListener):
    """`CallbackQueryListener` whose presses cancel the message listen tied to the pressed message.

    After a press is resolved, and when `cancel_policy` allows it, the
    client's message listener (`Client.message_listen`) is searched for the
    waits tied to the pressed message: their `context.message_id` is that
    message's id, as `ask` records it. Each ends with `ListenerCancelled`.
    Only message waits are cancelled, and only those aimed at the presser or
    at anyone in the chat.

    For example, a question sent with `ask` can carry a "back" button: a
    press on it ends the wait for the text answer.

    Example:
        >>> import asyncio
        >>> from types import SimpleNamespace
        >>> from pyrogram.types import CallbackQuery, Chat, User
        >>> from pyroflow.errors import ListenerCancelled
        >>> from pyroflow.models import ListenerContext
        >>> from pyroflow.update_listener import MessageListener
        >>> async def main():
        ...     messages = MessageListener()
        ...     context = ListenerContext(message_id=3)
        ...     waiter = asyncio.create_task(messages.listen(1, 2, context=context))
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

    def __init__(
        self,
        *args: Any,
        cancel_policy: MessageListenCancelPolicy = MessageListenCancelPolicy.UNRESOLVED,
        **kw: Any,
    ) -> None:
        """Initialize the listener.

        Args:
            *args: Passed to `CallbackQueryListener`.
            cancel_policy: Which presses cancel: every press, only those no
                callback wait took (the default), or only those one took.
            **kw: Passed to `CallbackQueryListener`.
        """
        super().__init__(*args, **kw)

        self.cancel_policy = cancel_policy
        """Which presses cancel the message listen tied to the pressed message."""

    async def resolve(self, update: CallbackQuery) -> bool:
        """Resolve the callback, then cancel the message listen on its message if `cancel_policy` allows.

        Args:
            update: The incoming callback query.

        Returns:
            Whether a callback listener took the update.
        """
        resolved = await super().resolve(update)
        policy = self.cancel_policy

        if (
            policy is MessageListenCancelPolicy.ALWAYS
            or (policy is MessageListenCancelPolicy.RESOLVED and resolved)
            or (policy is MessageListenCancelPolicy.UNRESOLVED and not resolved)
        ):
            self._cancel_message_listen(update)

        return resolved

    def _cancel_message_listen(self, update: CallbackQuery) -> None:
        """Cancel every message listen tied to the pressed message.

        The candidates are the sub-keys of `(chat, presser, pressed message)`,
        so a press only ends waits aimed at the presser or at anyone in the
        chat; each whose `context.message_id` is the pressed message's id is
        cancelled. Nothing is cancelled when the callback carries no message,
        chat or message id, or the client has no message listener.

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

            if listener is not None and listener.context.message_id == m.id:
                m_listen.cancel(sub)


__all__ = ("MessageListenCancellingCallbackQueryListener",)
