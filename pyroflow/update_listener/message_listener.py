"""Listener for message updates, with optional bot-command bypass."""

from __future__ import annotations as _annotations

import re
import weakref
from typing import Any, Final, cast, TYPE_CHECKING

from pytrove import safe_await

from ..models import ListenerKey
from ..types import Message
from .update_listener import UpdateListener

if TYPE_CHECKING:
    from pyrogram.types import Chat

    from ..client import Client


_COMMAND_RE: Final[re.Pattern[str]] = re.compile(
    r"^/([a-zA-Z][a-zA-Z0-9_]{0,31})(?:@(\w+))?(?:\s|$)"
)
"""Telegram command syntax: `/name` with an optional `@username`, capturing both."""


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
    _bot_commands_cache: dict[int, frozenset[str]]
    """Lowercased bot command names per client, keyed by `id(client)`."""

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

            self._bot_commands_cache = {}

    async def stop(self) -> None:
        """Stop the listener and clear the cached bot commands."""
        try:
            return await super().stop()
        finally:
            self._bot_commands_cache.clear()

    async def _is_listenable(self, update: Message) -> bool:
        """Return whether `_extract_key` keys the message: incoming, from other users.

        Args:
            update: The incoming message.

        Returns:
            `False` for outgoing, service, empty or edited messages, messages
            sent by this account, and messages without a chat; `True` otherwise.
        """
        return not (
            update.outgoing
            or update.service
            or getattr(update.from_user, "is_self", False)
            or update.empty
            or update.edit_date
            or update.edit_hidden
            or update.chat is None
        )

    async def _extract_key(self, update: Message) -> ListenerKey | None:
        """Default `extract_key_func`: key the message by chat, sender and id.

        Args:
            update: The incoming message.

        Returns:
            The key `(chat id, sender id or None, message id)`, or `None` if
            `_is_listenable` rejects the message.
        """
        if not await self._is_listenable(update):
            return None

        # `_is_listenable` يضمن أن `chat` ليس `None`؛ `from_user` قد يكون `None` (مشرف مجهول، منشور قناة)
        return ListenerKey(
            cast("Chat", update.chat).id,  # ty: ignore[invalid-argument-type]  # pyrogram types `Chat.id` as `int | None`; a received chat always has an id
            getattr(update.from_user, "id", None),
            update.id,
        )

    async def _is_bypass(self, update: Message) -> bool:
        """Ready-made `is_bypass_func` that bypasses registered bot commands.

        The text or caption must follow Telegram's command syntax: `/name`
        (1-32 letters, digits or underscores, starting with a letter),
        optionally followed by `@username`, then whitespace or the end of the
        text. A command aimed at another username, or not among the bot's
        registered commands (see `_get_bot_commands`), does not bypass, so
        nothing bypasses on a user account or when the fetch failed.

        Not wired in by default: assign it to `is_bypass_func` on the
        constructed listener to opt in.

        Args:
            update: The incoming message, already matched to a listener.

        Returns:
            `True` if the text or caption is a registered command of this
            bot, `False` otherwise.

        Example:
            >>> import asyncio
            >>> from pyrogram.types import Chat
            >>> listener = MessageListener()
            >>> listener.is_bypass_func = listener._is_bypass
            >>> update = Message(id=1, chat=Chat(id=1), text="/usr/bin")
            >>> asyncio.run(listener.is_bypass(update))
            False
        """
        match = _COMMAND_RE.match(update.text or update.caption or "")

        if not match:
            return False

        name, target = match.group(1).lower(), match.group(2)
        client = update._client

        if target is not None:
            me_usernames = frozenset(
                [(getattr(client.me, "username", None) or "").lower()]
                + [u.username.lower() for u in (getattr(client.me, "usernames", None) or [])]
            )

            if target.lower() not in me_usernames:
                return False

        return name in await self._get_bot_commands(client)

    async def _get_bot_commands(self, client: Client) -> frozenset[str]:
        """Return the bot's officially registered command names, lowercased.

        Fetched with `client.get_bot_commands()` at most once per client; the
        cache is cleared in `stop` and dropped when the client is
        garbage-collected. A failed fetch (such as on a user account) is
        cached as an empty set, so it is not retried.

        Args:
            client: The client whose bot commands are wanted.

        Returns:
            The lowercased command names, empty if the fetch failed.
        """
        commands = self._bot_commands_cache.get(id(client))

        if commands is None:
            result = await safe_await(client.get_bot_commands())
            cmds = () if isinstance(result, BaseException) else result

            self._bot_commands_cache[id(client)] = commands = frozenset(
                c.command.lower() for c in cmds
            )
            weakref.finalize(client, self._bot_commands_cache.pop, id(client), None)

        return commands


__all__ = ("MessageListener",)
