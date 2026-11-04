"""Listener for callback query updates."""

from __future__ import annotations as _annotations

from typing import Any, TYPE_CHECKING

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

    async def on_unresolved(self, update: CallbackQuery) -> None:
        """Cancel the message listener waiting on this callback's message, then raise.

        Only the first message listener matching one of the sub-keys of the
        callback's `extract_key` is considered, and it is cancelled only if its
        `meta["message_id"]` equals the callback's message id. Nothing is
        cancelled when the callback carries no message id, `extract_key`
        returns `None`, or the client has no message listener.

        Args:
            update: The incoming callback query.

        Raises:
            UnresolvedUpdate: Always, via the base implementation.
        """
        client = update._client
        m = update.message

        if not m or not getattr(m, "id", None):
            return await super().on_unresolved(update)

        key = await self.extract_key(update)

        if key is None:
            return await super().on_unresolved(update)

        try:
            m_listen = client.message_listen
        except KeyError:
            pass
        else:
            m_listeners = m_listen.listeners

            for sub in key.sub_keys():
                if listener := m_listeners.get(sub):
                    if isinstance(listener.meta, dict) and listener.meta.get("message_id") == m.id:
                        await m_listen.cancel(sub)
                    break

        return await super().on_unresolved(update)


__all__ = ("CallbackQueryListener",)
