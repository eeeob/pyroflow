"""Listener for callback query updates."""

from __future__ import annotations as _annotations

from typing import TYPE_CHECKING

from ..models import CallbackQueryKey
from ..types import CallbackQuery
from .update_listener import UpdateListener

if TYPE_CHECKING:
    import sys

    if sys.version_info >= (3, 11):
        from typing import Unpack
    else:
        from typing_extensions import Unpack

    from .update_listener import ListenKw


class CallbackQueryListener(UpdateListener[CallbackQuery, CallbackQueryKey]):
    """Listener keyed by the chat, user and message a callback query belongs to.

    Example:
        >>> import asyncio
        >>> from pyrogram.types import Chat, Message, User
        >>> async def main():
        ...     listener = CallbackQueryListener()
        ...     waiter = asyncio.create_task(listener.listen(chat_id=1, user_id=2, message_id=3))
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

    if not TYPE_CHECKING:

        def __init__(self, *args: object, **kw: object) -> None:
            """Initialize the listener, defaulting to `CallbackQueryKey.from_callback_query`.

            Args:
                *args: Passed to `UpdateListener`.
                **kw: Passed to `UpdateListener`.
            """
            super().__init__(*args, **kw)

            if self.extract_key_func is None:
                self.extract_key_func = self.__key_type__.from_callback_query

    async def listen(  # ty: ignore[invalid-method-override]  # takes the key fields; `UpdateListener.listen` takes the whole key
        self,
        chat_id: int | None = None,
        user_id: int | None = None,
        message_id: int | None = None,
        inline_message_id: str | None = None,
        ephemeral: bool = False,
        **kw: Unpack[ListenKw],
    ) -> CallbackQuery:
        """Wait for the next press matching the given fields; `None` matches any value.

        Also callable as `listener(...)`. See `UpdateListener.listen` for the
        arguments of the wait and the errors.

        Args:
            chat_id: The chat to listen in; a user's private chat has the
                user's id. A press on an inline-mode message has no chat.
            user_id: The user to wait for.
            message_id: The message whose buttons to wait on.
            inline_message_id: The inline-mode message whose buttons to wait
                on.
            ephemeral: Wait on presses on ephemeral messages, the only wait
                they reach.
            **kw: The arguments of the wait, as `UpdateListener.listen` takes them.

        Returns:
            The matching callback query.
        """
        return await super().listen(
            self.__key_type__(
                chat_id=chat_id,
                user_id=user_id,
                message_id=message_id,
                inline_message_id=inline_message_id,
                ephemeral=ephemeral,
            ),
            **kw,
        )

    __call__ = listen  # ty: ignore[invalid-method-override]  # takes the key fields; `UpdateListener.listen` takes the whole key
    """Alias of `listen`, so the listener can be awaited as `listener(...)`."""


__all__ = ("CallbackQueryListener",)
