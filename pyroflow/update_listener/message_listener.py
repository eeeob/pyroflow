"""Listener for message updates, with optional bot-command bypass."""

from __future__ import annotations as _annotations

import logging
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

log = logging.getLogger(__name__)


class MessageListener(UpdateListener[Message]):
    """Listener keyed by the chat, sender and id of incoming messages."""

    __update_type__ = Message
    _bot_commands_cache: dict[int, frozenset[str]]

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

            self._bot_commands_cache = {}

    async def stop(self) -> None:
        """Stop the listener and clear the cached bot commands."""
        try:
            return await super().stop()
        finally:
            self._bot_commands_cache.clear()

    async def _is_listenable(self, update: Message) -> bool:
        """Default ``is_listenable_func``: accept incoming messages from other users.

        Args:
            update: The incoming message.

        Returns:
            ``False`` for outgoing, service, empty or edited messages, messages
            sent by this account, and messages without a chat; ``True`` otherwise.
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

    async def _extract_key(self, update: Message) -> ListenerKey:
        """Default ``extract_key_func``: key the message by chat, sender and id.

        Args:
            update: The incoming message.

        Returns:
            The key ``(chat id, sender id or None, message id)``.
        """
        # `_is_listenable` يضمن أن `chat` ليس `None`؛ `from_user` قد يكون `None` (مشرف مجهول، منشور قناة)
        return ListenerKey(
            cast("Chat", update.chat).id,  # ty: ignore[invalid-argument-type]  # pyrogram types `Chat.id` as `int | None`; a received chat always has an id
            getattr(update.from_user, "id", None),
            update.id,
        )

    async def _is_bypass(self, update: Message) -> bool:
        """Ready-made ``bypass_func`` that bypasses registered bot commands.

        The update is treated as a bot command only if it matches Telegram's
        own command syntax — ``/name`` (1-32 letters, digits or underscores,
        starting with a letter), optionally targeted at ``@botusername``,
        followed by whitespace or end of text. A message that merely starts
        with ``/`` but does not match this shape (e.g. ``/`` alone, or a path
        like ``/usr/bin``) is not treated as a bypass. A command targeted at
        a username other than this account's is not a bypass either.

        The parsed command name must also be one of the bot's officially
        registered commands (see :meth:`_get_bot_commands`) — a command
        aimed at a different bot in the same group, a typo, or any
        syntactically valid command that was simply never registered, does
        not bypass the listener. If no commands are registered, or they
        cannot be determined at all (user account, or the fetch failed),
        nothing bypasses.

        Not wired in by default. It is a bound method, so opt in by
        assigning it to ``bypass_func`` on the constructed listener::

            listener = MessageListener()
            listener.bypass_func = listener._is_bypass

        Args:
            update: The incoming message, already matched to a listener.

        Returns:
            ``True`` if the text or caption is a registered command of this
            bot, ``False`` otherwise.
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

        Fetched via ``client.get_bot_commands()`` at most once per client
        for the listener's lifetime — cleared in :meth:`stop`, and dropped
        when the client is garbage-collected.

        A failed fetch (e.g. this session is a user account, not a bot —
        ``get_bot_commands`` is bot-only) is cached too, as an empty set, so
        it is only ever attempted once rather than on every message — an
        empty set means no command will ever be recognized as one.

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
