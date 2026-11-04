"""Listener for callback query updates."""

from __future__ import annotations as _annotations

from typing import Any, TYPE_CHECKING

from ..constants import ASK_MESSAGE_ID_META_KEY
from ..models import ListenerKey
from ..types import CallbackQuery, Message
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

        def __init__(self, *args: Any, **kw: Any) -> None:
            """Initialize the listener, defaulting to the built-in key functions.

            Args:
                *args: Passed to `UpdateListener`.
                **kw: Passed to `UpdateListener`.
            """
            super().__init__(*args, **kw)

            if self.extract_key_func is None:
                self.extract_key_func = self._extract_key

    async def _is_listenable(self, update: CallbackQuery) -> bool:
        """Return whether `_extract_key` keys the callback: attached to a message in a chat.

        Args:
            update: The incoming callback query.

        Returns:
            `True` if the callback has a message and that message has a chat.
        """
        m = update.message

        return m is not None and m.chat is not None

    async def _extract_key(self, update: CallbackQuery) -> ListenerKey | None:
        """Default `extract_key_func`: key the callback by chat, user and message.

        Args:
            update: The incoming callback query.

        Returns:
            The key `(message chat id, sender id, message id)`, or `None` if
            `_is_listenable` rejects the callback.
        """
        if not await self._is_listenable(update):
            return None

        m = update.message

        # `_is_listenable` يضمن أن `message` و `chat` ليسا `None` قبل استخراج المفتاح
        return ListenerKey(m.chat.id, update.from_user.id, m.id)  # ty: ignore[unresolved-attribute, invalid-argument-type]  # `_is_listenable` guarantees `message` and `chat` are set

    async def resolve(self, update: CallbackQuery) -> bool:
        """Resolve the callback; when no callback listener takes it, cancel the ask on its message.

        A button pressed on a message that a text `ask` waits on ends that
        ask: see `_cancel_prompted_ask`.

        Args:
            update: The incoming callback query.

        Returns:
            Whether a callback listener took the update.
        """
        resolved = await super().resolve(update)

        if not resolved:
            self._cancel_prompted_ask(update)

        return resolved

    def _cancel_prompted_ask(self, update: CallbackQuery) -> None:
        """Cancel the message listener whose `ask` sent or edited the pressed message.

        `ask` records that message's id in the listener's `meta` under
        `ASK_MESSAGE_ID_META_KEY`. The candidates are the sub-keys of
        `(chat, presser, pressed message)`, so a press only ends an ask aimed
        at the presser or at anyone in the chat; the first whose recorded id
        matches is cancelled. Nothing is
        cancelled when the callback carries no message, chat or message id, or
        the client has no message listener.

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

            if listener is not None and (listener.meta or {}).get(ASK_MESSAGE_ID_META_KEY) == m.id:
                m_listen.cancel(sub)
                return


__all__ = ("CallbackQueryListener",)
