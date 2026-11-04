"""The opt-in `BotCommandsMixin`, which publishes the bot commands of registered handlers."""

from __future__ import annotations as _annotations

import asyncio
from functools import cached_property
from typing import Any, TYPE_CHECKING

from pyrogram.sync import wrap as async_to_sync
from pytrove import (
    to_list,
    dedupe,
    gather_abort,
    clean_none_kw,
    safe_call,
)

from ..constants import BOT_COMMANDS_ATTR
from ..utils import split_bot_command_entry, mark_bot_commands

if TYPE_CHECKING:
    from pyrogram import Client as PyroClient
    from pyrogram.handlers.handler import Handler
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
    the commands of every registered handler after connecting (so `plugins`
    handlers are included), and `stop` deletes them before disconnecting. Each
    `(language_code, scope)` group is one Telegram call, so different scopes
    never overwrite each other. Only handlers added through `add_handler`
    count, as `plugins` handlers are; one placed on `dispatcher` directly is
    not seen.

    Warning:
        Telegram keeps one command list per bot, scope and language, with no
        owner. If two sessions of the same bot overlap, such as during a
        restart or a rolling deploy, the one that stops deletes the commands
        the other still uses. Stop with `remove_commands=False` there.
    """

    @cached_property
    def bot_command_groups(self) -> list[tuple[BotCommandGroupKeyT, list[BotCommand]]]:
        """The groups `push_bot_commands` last sent, as `((language_code, scope), commands)` pairs."""
        return []

    @cached_property
    def bot_command_groups_lock(self) -> asyncio.Lock:
        """Lock held while the commands are published or deleted."""
        return asyncio.Lock()

    @cached_property
    def _registered_handlers(self) -> list[tuple[Handler, int]]:
        """Every `(handler, group)` passed to `add_handler` and not yet removed, in call order."""
        return []

    def add_handler(self, handler: Handler, group: int = 0) -> tuple[Handler, int]:
        """Register `handler` as usual, and record it for `push_bot_commands`."""
        result = super().add_handler(handler, group)
        # Pyrogram يسجّل في task تنتظر أقفال الـ workers، وهي ممسوكة طوال تنفيذ كل handler
        # (ومنه انتظار `ask`)؛ فانتظار التسجيل قد يطول بلا حد، أو يتوقف للأبد إن جاء
        # من داخل handler. لذا نسجّل هنا فوراً، بالترتيب نفسه الذي ستنفّذ به tasks Pyrogram.
        self._registered_handlers.append((handler, group))
        return result

    def remove_handler(self, handler: Handler, group: int = 0) -> None:
        """Remove `handler` as usual, and drop its record, if it was added to `group`."""
        super().remove_handler(handler, group)
        # Pyrogram يتجاهل (`ValueError` داخل task) handler ليس في `group`، فنتجاهله مثله.
        safe_call(self._registered_handlers.remove, (handler, group), include_exc=ValueError)

    def _declared_bot_command_groups(self) -> list[tuple[BotCommandGroupKeyT, list[BotCommand]]]:
        """Group the commands every recorded handler declares.

        Returns:
            `((language_code, scope), commands)` pairs, each group deduplicated
            and non-empty, in registration order.
        """
        declared: list[tuple[BotCommandGroupKeyT, list[BotCommand]]] = []

        for handler, _ in self._registered_handlers:
            for entry in getattr(handler, BOT_COMMANDS_ATTR, ()):
                language_code, scope, commands = split_bot_command_entry(entry)
                key = (language_code, scope)
                group = next((_commands for _key, _commands in declared if _key == key), None)

                if group is None:
                    declared.append((key, group := []))

                group.extend(to_list(commands))

        # `BotCommand` يعرّف `__eq__` بلا `__hash__`
        return [
            (key, unique)
            for key, commands in declared
            if (unique := dedupe(commands, hashable=False))
        ]

    async def push_bot_commands(self) -> None:
        """Send the commands of every handler registered so far to Telegram.

        Each group is sent with `set_bot_commands`, and a group sent before
        that no handler declares any more is deleted with
        `delete_bot_commands`. A handler counts as soon as `add_handler`
        returns, even if Pyrogram has not placed it yet, so this never waits
        on the dispatcher and is safe to call from a handler. Called by
        `start`.
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

    async def start(self, *args: Any, **kw: Any) -> PyroClient:
        """Start the client as usual, then publish the commands."""
        result = await super().start(*args, **kw)
        await self.push_bot_commands()
        return result

    async def stop(
        self, block: bool = True, clear_handlers: bool = True, *, remove_commands: bool = True
    ) -> PyroClient:
        """Delete the published commands, then stop the client as usual.

        Args:
            block: Passed to `pyrogram.Client.stop`.
            clear_handlers: Passed to `pyrogram.Client.stop`; when `True`, the
                handler records are dropped too, as Pyrogram drops the handlers.
            remove_commands: `False` keeps the commands on Telegram after stopping.
        """
        if remove_commands:
            await self.remove_bot_commands()

        result = await super().stop(block, clear_handlers)

        if clear_handlers:
            self._registered_handlers.clear()

        return result


async_to_sync(BotCommandsMixin)


__all__ = (
    "BotCommandsMixin",
    # Defined in `pyroflow.utils.bot_commands`; re-exported so `pyroflow` keeps offering it.
    "mark_bot_commands",
)
