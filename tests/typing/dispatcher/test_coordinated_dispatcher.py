"""Static type tests for `CoordinatedDispatcher`."""

from __future__ import annotations as _annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pyroflow import Client, CoordinatedDispatcher, Dispatcher

    def chat_key(update: object) -> int:
        return 1

    def _check_install(client: Client) -> None:
        dispatcher = CoordinatedDispatcher(
            client, key_functions=[chat_key, lambda update: update.__class__.__name__]
        )
        client.dispatcher = dispatcher
        base: Dispatcher = dispatcher  # a `Dispatcher`, where the client keeps one
        assert base.client is client

    def _check_rejects(client: Client) -> None:
        CoordinatedDispatcher(client, key_functions=[1])  # ty: ignore[invalid-argument-type]
