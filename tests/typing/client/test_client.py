"""Static type tests for ``pyroflow.client.client``."""

from __future__ import annotations as _annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing_extensions import assert_type

    from pyrogram.types import InputRichMessage

    from pyroflow import CallbackQuery, Client, Message
    from pyroflow.enums import WorkersBusyMode
    from pyroflow.models import WorkersPolicy

    def _check_with_workers_policy(client: Client) -> None:
        policy = WorkersPolicy(WorkersBusyMode.REJECT)
        assert_type(client.with_workers_policy(policy), Client)
        assert_type(client.with_workers_policy(None), Client)

    async def _check_ask_send(client: Client) -> None:
        assert_type(await client.ask(1, "hi"), Message)
        assert_type(await client.ask("chat", "hi", listen_update_type=Message), Message)
        assert_type(await client.ask(1, "hi", listen_update_type=CallbackQuery), CallbackQuery)

    async def _check_ask_edit(client: Client) -> None:
        assert_type(await client.ask(1, "hi", 5), Message)
        assert_type(await client.ask(1, "hi", 5, listen_update_type=CallbackQuery), CallbackQuery)

    async def _check_ask_pyrogram_arguments(client: Client) -> None:
        await client.ask(1, "hi", disable_notification=True, listen_timeout=5)
        await client.ask(1, "hi", ephemeral_message_parameters=None, reply_to_message_id=3)
        await client.ask(1, "hi", 5, parse_mode=None, business_connection_id="bc")
        await client.ask(1, "hi", disable_notification="yes")  # ty: ignore[invalid-argument-type]

    async def _check_ask_rejects(client: Client) -> None:
        await client.ask(1, "hi", listen_update_type=int)  # ty: ignore[no-matching-overload]
        await client.ask(1, "hi", "5")  # ty: ignore[invalid-argument-type]

    async def _check_ask_rich_send(client: Client, rich: InputRichMessage) -> None:
        assert_type(await client.ask_rich(1, rich), Message)
        assert_type(await client.ask_rich("chat", rich, listen_update_type=Message), Message)
        assert_type(await client.ask_rich(1, rich, listen_update_type=CallbackQuery), CallbackQuery)

    async def _check_ask_rich_edit(client: Client, rich: InputRichMessage) -> None:
        assert_type(await client.ask_rich(1, rich, 5), Message)
        assert_type(
            await client.ask_rich(1, rich, 5, listen_update_type=CallbackQuery), CallbackQuery
        )

    async def _check_ask_rich_rejects(client: Client, rich: InputRichMessage) -> None:
        await client.ask_rich(1, rich, listen_update_type=int)  # ty: ignore[no-matching-overload]
        await client.ask_rich(1, "hi")  # ty: ignore[invalid-argument-type]
        await client.ask_rich(1, rich, "5")  # ty: ignore[invalid-argument-type]
