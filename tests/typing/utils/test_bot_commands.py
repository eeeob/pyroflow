"""Static type tests for ``pyroflow.utils.bot_commands``."""

from __future__ import annotations as _annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pyrogram.types import BotCommand, BotCommandScopeAllPrivateChats
    from typing_extensions import assert_type

    from pyroflow import Client, Message
    from pyroflow.utils import mark_bot_commands

    async def _check_preserves_function(client: Client, message: Message) -> None:
        command = BotCommand("start", "Start")
        scope = BotCommandScopeAllPrivateChats()

        @mark_bot_commands(command)
        async def handler(c: Client, m: Message) -> int:
            return 1

        assert_type(await handler(client, message), int)

        @mark_bot_commands([command], (scope, command), ("en", scope, [command]))
        def sync_handler(c: Client, m: Message) -> str:
            return ""

        assert_type(sync_handler(client, message), str)
        sync_handler(client)  # ty: ignore[missing-argument]

    def _check_rejects() -> None:
        mark_bot_commands("start")  # ty: ignore[invalid-argument-type]
