"""Static type tests for ``pyroflow.client``."""

from __future__ import annotations as _annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing_extensions import assert_type

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
