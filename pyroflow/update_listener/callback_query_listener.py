"""Listener for callback query updates."""

from __future__ import annotations as _annotations

from typing import Any, TYPE_CHECKING

from ..models import ListenerKey
from ..types import CallbackQuery
from .update_listener import UpdateListener


class CallbackQueryListener(UpdateListener[CallbackQuery]):
    """Listener keyed by the chat, user and message a callback query belongs to."""

    __update_type__ = CallbackQuery

    if not TYPE_CHECKING:

        def __init__(self, *args: Any, **kw: Any) -> None:
            """Initialize the listener, defaulting to the built-in key functions.

            Args:
                *args: Passed to :class:`UpdateListener`.
                **kw: Passed to :class:`UpdateListener`.
            """
            super().__init__(*args, **kw)

            if self.is_listenable_func is None:
                self.is_listenable_func = self._is_listenable

            if self.extract_key_func is None:
                self.extract_key_func = self._extract_key

    async def _is_listenable(self, update: CallbackQuery) -> bool:
        """Default ``is_listenable_func``: accept callbacks attached to a message in a chat.

        Args:
            update: The incoming callback query.

        Returns:
            ``True`` if the callback has a message and that message has a chat.
        """
        m = update.message

        return m is not None and m.chat is not None

    async def _extract_key(self, update: CallbackQuery) -> ListenerKey:
        """Default ``extract_key_func``: key the callback by chat, user and message.

        Args:
            update: The incoming callback query.

        Returns:
            The key ``(message chat id, sender id, message id)``.
        """
        m = update.message

        # `_is_listenable` يضمن أن `message` و `chat` ليسا `None` قبل استخراج المفتاح
        return ListenerKey(m.chat.id, update.from_user.id, m.id)  # ty: ignore[unresolved-attribute, invalid-argument-type]  # `_is_listenable` guarantees `message` and `chat` are set

    async def on_unresolved(self, key: ListenerKey, update: CallbackQuery) -> None:
        """Cancel the message listener waiting on this callback's message, then raise.

        The client's message listeners are searched for the first one
        matching one of ``key``'s sub-keys; it is cancelled only if its
        ``meta["message_id"]`` equals the callback's message id. Nothing is
        cancelled when the callback carries no message id or the client
        has no message listener.

        Args:
            key: The extracted key that had no matching callback listener.
            update: The incoming callback query.

        Raises:
            UnresolvedUpdate: Always, via the base implementation.
        """
        client = update._client
        m = update.message

        if not m or not getattr(m, "id", None):
            return await super().on_unresolved(key, update)

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

        return await super().on_unresolved(key, update)


__all__ = ("CallbackQueryListener",)
