"""Static type tests for ``pyroflow.update_listener.update_listener``."""

from __future__ import annotations as _annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing_extensions import assert_type

    from pyroflow import (
        CallbackQuery,
        CallbackQueryListener,
        Message,
        MessageListener,
        UpdateListener,
    )

    async def _check_listen(
        messages: MessageListener,
        queries: CallbackQueryListener,
        generic: UpdateListener[Message],
    ) -> None:
        assert_type(await messages.listen(1), Message)
        assert_type(await messages.listen(1, 2, 3, {"k": 1}, timeout=1.5), Message)
        assert_type(await messages(1), Message)
        assert_type(await queries.listen(1), CallbackQuery)
        assert_type(await queries(1, message_id=3), CallbackQuery)
        assert_type(await generic.listen(1), Message)

    async def _check_listen_rejects(messages: MessageListener) -> None:
        await messages.listen("1")  # ty: ignore[invalid-argument-type]
        await messages.listen(1, 2, 3, None, 5)  # ty: ignore[too-many-positional-arguments]

    def _check_listener_bound() -> None:
        UpdateListener[int]  # ty: ignore[invalid-type-arguments]


def test_type_checks_are_not_defined_at_runtime() -> None:
    assert "_check_listen" not in globals()
