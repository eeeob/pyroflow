from typing import TYPE_CHECKING, FrozenSet, Dict

from ..utils import safe_await, is_exception
from ..models import ListenerKey
from ..types import Message

from .update_listener import UpdateListener

if TYPE_CHECKING:
    from ..client import Client

import re
import logging
import weakref

log = logging.getLogger(__name__)


_COMMAND_RE = re.compile(r"^/([a-zA-Z][a-zA-Z0-9_]{0,31})(?:@(\w+))?(?:\s|$)")



class MessageListener(UpdateListener[Message]):
    __update_type__ = Message
    _bot_commands_cache: Dict[int, FrozenSet[str]]

    if not TYPE_CHECKING:
        def __init__(self, *args, **kw):
            super().__init__(*args, **kw)

            if self.is_listenable_func is None:
                self.is_listenable_func = self._is_listenable

            if self.extract_key_func is None:
                self.extract_key_func = self._extract_key

            self._bot_commands_cache = {}

    async def stop(self):
        try:
            return await super().stop()
        finally:
            self._bot_commands_cache.clear()

    async def _is_listenable(self, update):
        return not (
            update.outgoing 
            or update.service 
            or getattr(update.from_user, "is_self", False) 
            or update.empty 
            or update.edit_date 
            or update.edit_hidden 
            or update.chat is None
        )

    async def _extract_key(self, update):
        return ListenerKey(
            update.chat.id,
            update.from_user.id,
            update.id
        )

    async def _is_bypass(self, update):
        """
        Ready-made ``bypass_func``: treats the update as a bot command only
        if it matches Telegram's own command syntax — ``/name`` (1-32 word
        characters, starting with a letter), optionally targeted at
        ``@botusername``, followed by whitespace or end of text. A message
        that merely starts with ``/`` but does not match this shape (e.g.
        ``/`` alone, or a path like ``/usr/bin``) is not treated as a bypass.

        The parsed command name must also be one of the bot's officially
        registered commands (see :meth:`_get_bot_commands`) — a command
        aimed at a different bot in the same group, a typo, or any
        syntactically valid command that was simply never registered, does
        not bypass the listener. If no commands are registered, or they
        cannot be determined at all (user account, or the fetch failed),
        nothing bypasses.

        Not wired in by default — pass it explicitly to opt in::

            listener = MessageListener()
            listener.bypass_func = listener._is_bypass

        or, equivalently, at construction time::

            MessageListener(bypass_func=lambda update: ...)
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


    async def _get_bot_commands(self, client: "Client") -> FrozenSet[str]:
        """
        The bot's officially registered command names (lowercased), fetched
        via ``client.get_bot_commands()`` at most once per listener
        lifetime — cleared in :meth:`stop`.

        A failed fetch (e.g. this session is a user account, not a bot —
        ``get_bot_commands`` is bot-only) is cached too, as an empty set, so
        it is only ever attempted once rather than on every message — an
        empty set means no command will ever be recognized as one.
        """

        commands = self._bot_commands_cache.get(id(client))

        if commands is None:
            cmds = await safe_await(client.get_bot_commands())
            if is_exception(cmds):
                cmds = ()
 
            self._bot_commands_cache[id(client)] = commands = frozenset(c.command.lower() for c in cmds)
            weakref.finalize(client, self._bot_commands_cache.pop, id(client), None)

        return commands