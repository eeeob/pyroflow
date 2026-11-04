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
    safe_await,
    yield_control,
)

from ..constants import BOT_COMMANDS_ATTR
from ..utils import split_bot_command_entry, mark_bot_commands

if TYPE_CHECKING:
    from pyrogram import Client as PyroClient
    from pyrogram.handlers.handler import Handler
    from pyrogram.types import BotCommand, BotCommandScope
    from pytrove.typings import MaybeList

    from ..typings import BotCommandGroupKeyT
    from .client import Client


if TYPE_CHECKING:
    _BotCommandsMixinBase = Client
    """Base of `BotCommandsMixin`: `Client` for type checkers so calls like `self.set_bot_commands()` resolve, plain `object` at runtime."""
else:
    _BotCommandsMixinBase = object


class BotCommandsMixin(_BotCommandsMixinBase):
    """Opt-in `Client` mixin that publishes the bot commands of registered handlers.

    The commands are the ones declared with `mark_bot_commands`. Put the mixin
    first, as in `class MyClient(BotCommandsMixin, Client)`. Commands are
    collected as handlers are added or removed, published by `start` after
    connecting (so `plugins` handlers are included) and deleted by `stop`
    before disconnecting. Each `(language_code, scope)` group is one Telegram
    call, so different scopes never overwrite each other.
    """

    @cached_property
    def bot_command_groups(self) -> list[tuple[BotCommandGroupKeyT, list[BotCommand]]]:
        """Collected commands, as `((language_code, scope), commands)` pairs."""
        return []

    @cached_property
    def bot_command_groups_lock(self) -> asyncio.Lock:
        """Lock held while `bot_command_groups` is updated, published or deleted."""
        return asyncio.Lock()

    def add_handler(self, handler: Handler, group: int = 0) -> tuple[Handler, int]:
        """Register `handler` as usual, then collect the bot commands marked on it.

        The commands are collected in a later task, once the registration has
        landed; nothing is sent to Telegram yet.
        """
        result = super().add_handler(handler, group)
        self._track_bot_commands(handler, True)
        return result

    def remove_handler(self, handler: Handler, group: int = 0) -> None:
        """Remove `handler` as usual, then drop the bot commands marked on it.

        The commands are dropped in a later task, only if the handler was
        really removed; nothing is sent to Telegram yet.
        """
        result = super().remove_handler(handler, group)
        self._track_bot_commands(handler, False)
        return result

    def _track_bot_commands(self, handler: Handler, added: bool) -> None:
        """Schedule a task that collects or drops the commands of `handler`.

        The task runs after Pyrogram's own registration task and changes
        nothing unless `dispatcher.groups` really reflects the change.
        """
        # Pyrogram ينفّذ `add_handler`/`remove_handler` في task تأخذ `dispatcher.locks_list`،
        # وقد لا تفعل شيئاً (`ValueError` داخلها)؛ لذا نقرأ الحالة الفعلية في task تُجدول بعدها.

        async def apply() -> None:
            """Collect or discard the commands of `handler` if its registration really changed."""
            if not getattr(handler, BOT_COMMANDS_ATTR, ()):
                return

            if (
                any(handler in handlers for handlers in self.dispatcher.groups.values())
                is not added
            ):
                return

            locks = [self.bot_command_groups_lock] + self.dispatcher.locks_list
            acquired = []

            try:
                for lock in locks:
                    await lock.acquire()
                    acquired.append(lock)

                track = self._collect_bot_commands if added else self._discard_bot_commands

                for entry in getattr(handler, BOT_COMMANDS_ATTR, ()):
                    track(*split_bot_command_entry(entry))
            finally:
                # Release only what was acquired: `asyncio.Lock` has no owner, so
                # releasing a lock we were still waiting on when cancelled would
                # release it out from under its real holder.
                for lock in reversed(acquired):
                    lock.release()

        self.loop.create_task(apply())

    def _collect_bot_commands(
        self,
        language_code: str | None,
        scope: BotCommandScope | None,
        commands: MaybeList[BotCommand],
    ) -> None:
        """Add `commands` to the `(language_code, scope)` group, creating it if new."""
        key = (language_code, scope)
        bot_command_groups = self.bot_command_groups
        group = next((_commands for _key, _commands in bot_command_groups if _key == key), None)

        if group is None:
            bot_command_groups.append((key, group := []))

        group.extend(to_list(commands))

    def _discard_bot_commands(
        self,
        language_code: str | None,
        scope: BotCommandScope | None,
        commands: MaybeList[BotCommand],
    ) -> None:
        """Remove `commands` from the `(language_code, scope)` group, dropping it once empty."""
        key = (language_code, scope)

        for i, (_key, _commands) in enumerate(self.bot_command_groups):
            if _key != key:
                continue

            for command in to_list(commands):
                safe_call(_commands.remove, command, include_exc=ValueError)

            if not _commands:
                self.bot_command_groups.pop(i)

            break

    def _prune_bot_commands(self) -> None:
        """Drop every collected command that no registered handler declares any more.

        Never adds commands. Call it while holding `bot_command_groups_lock`,
        after yielding once so queued registrations have landed.
        """
        # قراءة `dispatcher.groups` بلا أقفاله مقصودة: لا task تتبّع يمكن أن تعمل في هذه الحالة.
        declared: list[tuple[BotCommandGroupKeyT, list[BotCommand]]] = []

        for handlers in list(self.dispatcher.groups.values()):
            for handler in handlers:
                for entry in getattr(handler, BOT_COMMANDS_ATTR, ()):
                    language_code, scope, commands = split_bot_command_entry(entry)
                    key = (language_code, scope)
                    group = next((_commands for _key, _commands in declared if _key == key), None)

                    if group is None:
                        declared.append((key, group := []))

                    group.extend(to_list(commands))

        groups = self.bot_command_groups

        if not declared:
            groups.clear()

        for i in reversed(range(len(groups))):
            key, commands = groups[i]
            live = next((_commands for _key, _commands in declared if _key == key), ())

            commands[:] = [command for command in commands if command in live]

            if not commands:
                groups.pop(i)

    async def push_bot_commands(self) -> None:
        """Send every collected command group to Telegram with `set_bot_commands`.

        Commands whose handler is gone are pruned first, duplicates within a
        group are sent once, and empty groups are skipped. Called by `start`.
        """
        await safe_await(yield_control(), self.bot_command_groups_lock.acquire(), return_exc=False)

        coros = []

        try:
            self._prune_bot_commands()
            for (language_code, scope), commands in self.bot_command_groups:
                # `BotCommand` يعرّف `__eq__` بلا `__hash__`
                unique = dedupe(commands, hashable=False)

                if not unique:
                    continue

                coros.append(
                    self.set_bot_commands(
                        unique, **clean_none_kw(scope=scope, language_code=language_code)
                    )
                )

            if coros:
                await gather_abort(coros)
        finally:
            self.bot_command_groups_lock.release()

    async def remove_bot_commands(self) -> None:
        """Delete every collected command group from Telegram with `delete_bot_commands`.

        Called by `stop` unless `remove_commands` is `False`.
        """
        await safe_await(yield_control(), self.bot_command_groups_lock.acquire(), return_exc=False)

        try:
            await gather_abort(
                self.delete_bot_commands(**clean_none_kw(language_code=language_code, scope=scope))
                for (language_code, scope), _ in self.bot_command_groups
            )
        finally:
            self.bot_command_groups_lock.release()

    async def start(self, *args: Any, **kw: Any) -> PyroClient:
        """Start the client as usual, then publish the collected commands."""
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
        try:
            return await super().stop(*args, **kw)
        finally:
            self._prune_bot_commands()


async_to_sync(BotCommandsMixin)


__all__ = (
    "BotCommandsMixin",
    # Defined in `pyroflow.utils.bot_commands`; re-exported so `pyroflow` keeps offering it.
    "mark_bot_commands",
)
