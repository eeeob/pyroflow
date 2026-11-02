"""Tests for ``pyroflow.utils.bot_commands``."""

from __future__ import annotations as _annotations

from typing import Any

import pytest
from pyrogram import Client, filters, handlers
from pyrogram.handlers import CallbackQueryHandler, Handler, MessageHandler
from pyrogram.types import BotCommand, BotCommandScopeAllPrivateChats

from pyroflow.constants import BOT_COMMANDS_ATTR
from pyroflow.utils import bot_commands, mark_bot_commands, split_bot_command_entry


async def _callback(client: Any, update: Any) -> None:  # pragma: no cover - never called
    pass


# --- _MESSAGES_HANDLER ----------------------------------------------------


def test_messages_handler_holds_the_available_message_handler_types() -> None:
    expected = tuple(
        getattr(handlers, name)
        for name in ("MessageHandler", "BusinessMessageHandler")
        if hasattr(handlers, name)
    )

    assert bot_commands._MESSAGES_HANDLER == expected
    assert MessageHandler in bot_commands._MESSAGES_HANDLER
    assert all(issubclass(cls, Handler) for cls in bot_commands._MESSAGES_HANDLER)
    assert CallbackQueryHandler not in bot_commands._MESSAGES_HANDLER


# --- mark_bot_commands() --------------------------------------------------


def test_mark_bot_commands_stores_entries_on_message_handlers() -> None:
    cmd = BotCommand("start", "Start the bot")
    scoped = (BotCommandScopeAllPrivateChats(), [BotCommand("help", "Help")])
    message_handler = MessageHandler(_callback)

    async def func(client: Any, message: Any) -> None:  # pragma: no cover
        pass

    func.handlers = [(message_handler, 0)]  # type: ignore[attr-defined]

    assert mark_bot_commands(cmd, scoped)(func) is func
    assert getattr(message_handler, BOT_COMMANDS_ATTR) == (cmd, scoped)


def test_mark_bot_commands_marks_business_message_handlers() -> None:
    business_cls = getattr(handlers, "BusinessMessageHandler", None)
    if business_cls is None:  # pragma: no cover - depends on the installed fork
        pytest.skip("BusinessMessageHandler is not available")
    handler = business_cls(_callback)

    async def func(client: Any, message: Any) -> None:  # pragma: no cover
        pass

    func.handlers = [(handler, 1)]  # type: ignore[attr-defined]
    cmd = BotCommand("start", "Start")

    mark_bot_commands(cmd)(func)

    assert getattr(handler, BOT_COMMANDS_ATTR) == (cmd,)


def test_mark_bot_commands_leaves_other_handlers_untouched() -> None:
    message_handler = MessageHandler(_callback)
    callback_handler = CallbackQueryHandler(_callback)

    async def func(client: Any, update: Any) -> None:  # pragma: no cover
        pass

    func.handlers = [(callback_handler, 0), (message_handler, 0)]  # type: ignore[attr-defined]

    mark_bot_commands(BotCommand("start", "Start"))(func)

    assert not hasattr(callback_handler, BOT_COMMANDS_ATTR)
    assert hasattr(message_handler, BOT_COMMANDS_ATTR)


def test_mark_bot_commands_without_handlers_returns_func_unchanged() -> None:
    async def func(client: Any, message: Any) -> None:  # pragma: no cover
        pass

    assert mark_bot_commands(BotCommand("start", "Start"))(func) is func
    assert not hasattr(func, "handlers")


def test_mark_bot_commands_above_unbound_on_message() -> None:
    cmd = BotCommand("start", "Start the bot")

    @mark_bot_commands(cmd)
    @Client.on_message(filters.command("start"))
    async def on_start(client: Any, message: Any) -> None:  # pragma: no cover
        pass

    [(handler, _)] = on_start.handlers  # type: ignore[attr-defined]
    assert getattr(handler, BOT_COMMANDS_ATTR) == (cmd,)


# --- split_bot_command_entry() --------------------------------------------


def test_split_single_command() -> None:
    cmd = BotCommand("start", "Start")

    assert split_bot_command_entry(cmd) == (None, None, cmd)


def test_split_command_list() -> None:
    cmds = [BotCommand("start", "Start")]

    language_code, scope, commands = split_bot_command_entry(cmds)

    assert (language_code, scope) == (None, None)
    assert commands is cmds


def test_split_scope_and_commands_pair() -> None:
    scope = BotCommandScopeAllPrivateChats()
    cmds = [BotCommand("start", "Start")]

    result = split_bot_command_entry((scope, cmds))

    assert result == (None, scope, cmds)
    assert result[1] is scope and result[2] is cmds


def test_split_full_triple_is_returned_as_is() -> None:
    entry = ("en", BotCommandScopeAllPrivateChats(), BotCommand("start", "Start"))

    assert split_bot_command_entry(entry) is entry


def test_module_all_lists_public_names() -> None:
    assert bot_commands.__all__ == ("mark_bot_commands", "split_bot_command_entry")
