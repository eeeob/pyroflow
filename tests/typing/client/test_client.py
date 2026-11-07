"""Static type tests for ``pyroflow.client.client``."""

from __future__ import annotations as _annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing_extensions import assert_type

    from pyrogram.types import InputRichMessage

    from pyroflow import CallbackQuery, Client, Message
    from pyroflow.enums import WorkersPolicy

    def _check_setup_pyroflow(client: Client) -> None:
        policy = WorkersPolicy.REJECT
        assert_type(client.setup_pyroflow(workers_policy=policy), Client)
        assert_type(client.setup_pyroflow(ask_context_message=False), Client)
        assert_type(client.setup_pyroflow(), Client)

    async def _check_ask_message(client: Client) -> None:
        assert_type(await client.ask(1, "hi"), Message)
        assert_type(await client.ask("chat", "hi", listen_timeout=5), Message)
        assert_type(await client.ask(1, "hi", 5), Message)
        assert_type(await client.ask(1, "hi", message_id=5), Message)

    async def _check_ask_message_pyrogram_arguments(client: Client) -> None:
        await client.ask(1, "hi", disable_notification=True, listen_timeout=5)
        await client.ask(1, "hi", ephemeral_message_parameters=None, reply_to_message_id=3)
        await client.ask(1, "hi", 5, parse_mode=None)
        await client.ask(1, "hi", disable_notification="yes")  # ty: ignore[invalid-argument-type]

    async def _check_ask_message_rejects(client: Client) -> None:
        await client.ask(1, "hi", "5")  # ty: ignore[no-matching-overload]

    async def _check_ask_message_rich(client: Client, rich: InputRichMessage) -> None:
        assert_type(await client.ask_rich(1, rich), Message)
        assert_type(await client.ask_rich(1, rich, 5), Message)

    async def _check_ask_message_rich_rejects(client: Client, rich: InputRichMessage) -> None:
        await client.ask_rich(1, "hi")  # ty: ignore[invalid-argument-type]
        await client.ask_rich(1, rich, "5")  # ty: ignore[no-matching-overload]

    async def _check_ask_callback_query(client: Client) -> None:
        assert_type(await client.ask_callback_query(1, "hi"), CallbackQuery)
        assert_type(await client.ask_callback_query(1, "hi", 5), CallbackQuery)

    async def _check_ask_callback_query_rejects(client: Client) -> None:
        await client.ask_callback_query(1, "hi", "5")  # ty: ignore[no-matching-overload]

    async def _check_ask_callback_query_rich(client: Client, rich: InputRichMessage) -> None:
        assert_type(await client.ask_callback_query_rich(1, rich), CallbackQuery)
        assert_type(await client.ask_callback_query_rich(1, rich, 5), CallbackQuery)

    async def _check_ask_callback_query_rich_rejects(
        client: Client, rich: InputRichMessage
    ) -> None:
        await client.ask_callback_query_rich(1, "hi")  # ty: ignore[invalid-argument-type]
        await client.ask_callback_query_rich(1, rich, "5")  # ty: ignore[no-matching-overload]
