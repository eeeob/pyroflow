"""Static type tests for ``pyroflow.client.client``."""

from __future__ import annotations as _annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing_extensions import assert_type

    from pyrogram.types import InputRichMessage

    from pyroflow import CallbackQuery, Client, Message

    async def _check_ask_send(client: Client) -> None:
        assert_type(await client.ask(1, "hi"), Message)
        assert_type(await client.ask("chat", "hi", update_type=Message), Message)
        assert_type(await client.ask(1, "hi", update_type=CallbackQuery), CallbackQuery)

    async def _check_ask_edit(client: Client) -> None:
        assert_type(await client.ask(1, "hi", 5), Message)
        assert_type(await client.ask(1, "hi", 5, update_type=CallbackQuery), CallbackQuery)

    async def _check_ask_rejects(client: Client) -> None:
        await client.ask(1, "hi", update_type=int)  # ty: ignore[no-matching-overload]
        await client.ask(1, "hi", "5")  # ty: ignore[invalid-argument-type]

    async def _check_ask_rich_send(client: Client, rich: InputRichMessage) -> None:
        assert_type(await client.ask_rich(1, rich), Message)
        assert_type(await client.ask_rich("chat", rich, update_type=Message), Message)
        assert_type(await client.ask_rich(1, rich, update_type=CallbackQuery), CallbackQuery)

    async def _check_ask_rich_edit(client: Client, rich: InputRichMessage) -> None:
        assert_type(await client.ask_rich(1, rich, 5), Message)
        assert_type(await client.ask_rich(1, rich, 5, update_type=CallbackQuery), CallbackQuery)

    async def _check_ask_rich_rejects(client: Client, rich: InputRichMessage) -> None:
        await client.ask_rich(1, rich, update_type=int)  # ty: ignore[no-matching-overload]
        await client.ask_rich(1, "hi")  # ty: ignore[invalid-argument-type]
        await client.ask_rich(1, rich, "5")  # ty: ignore[invalid-argument-type]
