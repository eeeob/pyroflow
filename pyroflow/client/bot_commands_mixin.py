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
    yield_control,
)

from ..constants import BOT_COMMANDS_ATTR
from ..utils import split_bot_command_entry, mark_bot_commands

if TYPE_CHECKING:
    from pyrogram import Client as PyroClient
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
    never overwrite each other.

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

    async def _declared_bot_command_groups(
        self,
    ) -> list[tuple[BotCommandGroupKeyT, list[BotCommand]]]:
        """Group the commands every registered handler declares, once pending registrations land.

        Returns:
            `((language_code, scope), commands)` pairs, each group deduplicated
            and non-empty, in handler order.
        """
        # `add_handler`/`remove_handler` في Pyrogram تسجّل في task تأخذ أقفال `dispatcher.locks_list`
        # بالترتيب وتفكها في النهاية. نترك الـ loop تدور مرة لتبدأ كل task مجدولة قبلنا
        # فتأخذ الأقفال أو تقف في طابورها، ثم نأخذ الأقفال بالترتيب نفسه. `asyncio.Lock`
        # يخدم طابوره بالترتيب، فلا نحصل عليها إلا بعد انتهاء كل تسجيل سبقنا.
        await yield_control()
        acquired = []

        try:
            for lock in list(self.dispatcher.locks_list):
                await lock.acquire()
                acquired.append(lock)

            declared: list[tuple[BotCommandGroupKeyT, list[BotCommand]]] = []

            for handlers in self.dispatcher.groups.values():
                for handler in handlers:
                    for entry in getattr(handler, BOT_COMMANDS_ATTR, ()):
                        language_code, scope, commands = split_bot_command_entry(entry)
                        key = (language_code, scope)
                        group = next(
                            (_commands for _key, _commands in declared if _key == key), None
                        )

                        if group is None:
                            declared.append((key, group := []))

                        group.extend(to_list(commands))
        finally:
            # Release only what was acquired: `asyncio.Lock` has no owner, so
            # releasing a lock we were still waiting on when cancelled would
            # release it out from under its real holder.
            for lock in reversed(acquired):
                lock.release()

        # `BotCommand` يعرّف `__eq__` بلا `__hash__`
        return [
            (key, unique)
            for key, commands in declared
            if (unique := dedupe(commands, hashable=False))
        ]

    async def push_bot_commands(self) -> None:
        """Send the commands of every registered handler to Telegram.

        Each group is sent with `set_bot_commands`, and a group sent before
        that no handler declares any more is deleted with
        `delete_bot_commands`. Waits for registrations still pending. Called
        by `start`.
        """
        async with self.bot_command_groups_lock:
            groups = await self._declared_bot_command_groups()
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

    async def stop(self, *args: Any, remove_commands: bool = True, **kw: Any) -> PyroClient:
        """Delete the published commands, then stop the client as usual.

        Args:
            *args: Passed to `pyrogram.Client.stop`.
            remove_commands: `False` keeps the commands on Telegram after stopping.
            **kw: Passed to `pyrogram.Client.stop`.
        """
        if remove_commands:
            await self.remove_bot_commands()

        return await super().stop(*args, **kw)


async_to_sync(BotCommandsMixin)


__all__ = (
    "BotCommandsMixin",
    # Defined in `pyroflow.utils.bot_commands`; re-exported so `pyroflow` keeps offering it.
    "mark_bot_commands",
)
