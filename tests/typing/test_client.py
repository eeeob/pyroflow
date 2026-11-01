"""Static type tests for ``pyroflow.client``."""

from __future__ import annotations as _annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from typing_extensions import assert_type

    from pyroflow import CallbackQuery, Client, Message, MessageListener, UpdateListener

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
        await client.ask(1.5, "hi")  # ty: ignore[invalid-argument-type]

    def _check_listeners(client: Client) -> None:
        assert_type(client.message_listen, UpdateListener[Message])
        assert_type(client.callback_listen, UpdateListener[CallbackQuery])
        assert_type(client.listeners[Message], UpdateListener[Any])

    def _check_register_listener(client: Client, listener: MessageListener) -> None:
        client.register_listener(listener)
        client.register_listener(1)  # ty: ignore[invalid-argument-type]


def test_type_checks_are_not_defined_at_runtime() -> None:
    assert "_check_ask_send" not in globals()
