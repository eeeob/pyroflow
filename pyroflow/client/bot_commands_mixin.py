"""The opt-in `BotCommandsMixin`, which publishes the bot commands of registered handlers."""

from __future__ import annotations as _annotations

import asyncio
from functools import cached_property
from typing import Any, TYPE_CHECKING

from pyrogram import Client as PyroClient
from pyrogram.sync import wrap as async_to_sync
from pyrogram.types import BotCommandScopeDefault
from pytrove import (
    to_list,
    dedupe,
    gather_abort,
    clean_none_kw,
    safe_await,
)

from ..utils import split_bot_command_entry, mark_bot_commands
from ..utils.bot_commands import _BOT_COMMANDS_ATTR

if TYPE_CHECKING:
    from pyrogram.types import BotCommand

    from ..typings import BotCommandGroupKeyT
    from .client import Client


# Python has no intersection type for "this mixin and `Client`", which `self` and `super()` need.
if TYPE_CHECKING:
    _ClientForTypeCheckers = Client
    """`Client` as type checkers see the mixin's base; at runtime it is `object`, so the mixin does not inherit `Client`."""
else:
    _ClientForTypeCheckers = object


class BotCommandsMixin(_ClientForTypeCheckers):
    """Opt-in `Client` mixin that publishes the bot commands of registered handlers.

    The commands are the ones declared with `mark_bot_commands`. Put the mixin
    first, as in `class MyClient(BotCommandsMixin, Client)`. `start` publishes
    the commands of every registered handler once the `plugins` are loaded
    and the client is connected, and before the dispatcher starts (so the first
    updates already see them), and `stop` deletes them before disconnecting. Each
    `(language_code, scope)` group is one Telegram call, so different scopes
    never overwrite each other.

    Raises:
        TypeError: If `Client` does not come after this mixin in the class's MRO.

    Warning:
        Telegram keeps one command list per bot, scope and language, with no
        owner. If two sessions of the same bot overlap, such as during a
        restart or a rolling deploy, the one that stops deletes the commands
        the other still uses. Stop with `remove_commands=False` there.
    """

    if not TYPE_CHECKING:

        def __init__(self, *args: object, **kw: object) -> None:
            """Refuse a class without `Client` after this mixin, then initialise as usual.

            Args:
                *args: Passed to the next class in the MRO.
                **kw: Passed to the next class in the MRO.
            """
            mro = type(self).__mro__

            if PyroClient not in mro[mro.index(BotCommandsMixin) + 1 :]:
                msg = f"{type(self).__name__} must inherit Client after BotCommandsMixin"
                raise TypeError(msg)

            super().__init__(*args, **kw)

    @cached_property
    def bot_command_groups(self) -> list[tuple[BotCommandGroupKeyT, list[BotCommand]]]:
        """The groups `push_bot_commands` last sent, as `((language_code, scope), commands)` pairs."""
        return []

    @cached_property
    def bot_command_groups_lock(self) -> asyncio.Lock:
        """Lock held while the commands are published or deleted."""
        return asyncio.Lock()

    def _declared_bot_command_groups(self) -> list[tuple[BotCommandGroupKeyT, list[BotCommand]]]:
        """Group the commands every handler in `dispatcher.groups` declares.

        Entries Telegram files under the same list share a group: no scope
        and `BotCommandScopeDefault()` are both `None`, and no language and
        `""` are both `None`.

        Returns:
            `((language_code, scope), commands)` pairs, each group deduplicated
            and non-empty, in dispatcher order.
        """
        declared: list[tuple[BotCommandGroupKeyT, list[BotCommand]]] = []

        for handlers in self.dispatcher.groups.values():
            for handler in handlers:
                for entry in getattr(handler, _BOT_COMMANDS_ATTR, ()):
                    language_code, scope, commands = split_bot_command_entry(entry)
                    # Telegram reads no scope as the default scope, and no language as "".
                    key = (
                        language_code or None,
                        None if isinstance(scope, BotCommandScopeDefault) else scope,
                    )
                    group = next((_commands for _key, _commands in declared if _key == key), None)

                    if group is None:
                        declared.append((key, group := []))

                    group.extend(to_list(commands))

        # `BotCommand` defines `__eq__` without `__hash__`.
        return [
            (key, unique)
            for key, commands in declared
            if (unique := dedupe(commands, hashable=False))
        ]

    async def push_bot_commands(self) -> None:
        """Send the commands of every handler in `dispatcher.groups` to Telegram.

        Each group is sent with `set_bot_commands`, and a group sent before
        that no handler declares any more is deleted with
        `delete_bot_commands`. Called by `initialize`, which `start` runs.
        It is safe to call from a handler, and counts a handler added just
        before it.
        """
        async with self.bot_command_groups_lock:
            groups = self._declared_bot_command_groups()
            keys = [key for key, _ in groups]
            stale = [key for key, _ in self.bot_command_groups if key not in keys]
            # Recorded before sending, so `remove_bot_commands` covers a partly failed push.
            self.bot_command_groups[:] = groups

            await gather_abort(
                [
                    *(
                        self.delete_bot_commands(
                            **clean_none_kw(language_code=language_code, scope=scope)
                        )
                        for language_code, scope in stale
                    ),
                    *(
                        self.set_bot_commands(
                            commands, **clean_none_kw(scope=scope, language_code=language_code)
                        )
                        for (language_code, scope), commands in groups
                    ),
                ]
            )

    async def remove_bot_commands(self) -> None:
        """Delete every group `push_bot_commands` sent with `delete_bot_commands`.

        The groups are forgotten once deleted. Called by `stop` unless
        `remove_commands` is `False`.
        """
        async with self.bot_command_groups_lock:
            await gather_abort(
                [
                    self.delete_bot_commands(
                        **clean_none_kw(language_code=language_code, scope=scope)
                    )
                    for (language_code, scope), _ in self.bot_command_groups
                ]
            )
            self.bot_command_groups.clear()

    async def initialize(self, *args: Any, **kw: Any) -> None:
        """Publish the commands, then initialize the client as usual.

        `start` calls this once connected and its `plugins` loaded, and it
        starts the dispatcher, so no update is handled before the commands
        are published. A failure to publish, such as a command name Telegram
        rejects, is logged and does not fail `start`: the client is connected
        by then.

        Args:
            *args: Passed to `pyrogram.Client.initialize`.
            **kw: Passed to `pyrogram.Client.initialize`.
        """
        await safe_await(self.push_bot_commands(), return_exc=True, log_exc=True)
        await super().initialize(*args, **kw)

    async def stop(self, *args: Any, remove_commands: bool = True, **kw: Any) -> PyroClient:
        """Delete the published commands, then stop the client as usual.

        A failure to delete them, such as a lost connection, is logged and
        does not keep the client from stopping.

        Args:
            *args: Passed to `pyrogram.Client.stop`.
            remove_commands: `False` keeps the commands on Telegram after stopping.
            **kw: Passed to `pyrogram.Client.stop`.

        Returns:
            The client, as `pyrogram.Client.stop` returns it.
        """
        if remove_commands:
            await safe_await(self.remove_bot_commands(), return_exc=True, log_exc=True)

        return await super().stop(*args, **kw)


async_to_sync(BotCommandsMixin)


__all__ = (
    "BotCommandsMixin",
    # Defined in `pyroflow.utils.bot_commands`; re-exported so `pyroflow` keeps offering it.
    "mark_bot_commands",
)
