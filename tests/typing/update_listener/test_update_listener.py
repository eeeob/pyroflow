"""Static type tests for ``pyroflow.update_listener.update_listener``."""

from __future__ import annotations as _annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing_extensions import assert_type

    from pyroflow.models import (
        CallbackQueryKey,
        ListenerContext,
        ListenerKey,
        ListenerModel,
        MessageKey,
    )
    from pyroflow import (
        CallbackQuery,
        CallbackQueryListener,
        Message,
        MessageListener,
        UpdateListener,
    )
    from pyroflow.update_listener import ListenKw

    def _check_listen_kw() -> None:
        kw: ListenKw = {"context": ListenerContext(), "strict": True}
        assert_type(kw.get("timeout"), int | float | None)
        empty: ListenKw = {}
        bad: ListenKw = {"strict": "yes"}  # ty: ignore[invalid-argument-type]
        del empty, bad

    async def _check_listen(
        messages: MessageListener,
        queries: CallbackQueryListener,
        generic: UpdateListener[Message],
    ) -> None:
        assert_type(await messages.listen(MessageKey()), Message)
        assert_type(
            await messages.listen(
                MessageKey(1, 2, 3, 4, True),
                context=ListenerContext(k=1),
                timeout=1.5,
            ),
            Message,
        )
        assert_type(await messages(MessageKey(1)), Message)
        assert_type(await queries.listen(CallbackQueryKey(1)), CallbackQuery)
        assert_type(await queries(CallbackQueryKey(1, message_id=3), strict=True), CallbackQuery)
        assert_type(await generic.listen(MessageKey(1)), Message)

    def _check_keys(
        messages: MessageListener,
        queries: CallbackQueryListener,
        message: Message,
        query: CallbackQuery,
    ) -> None:
        assert_type(messages.extract_key(message), ListenerKey[Message] | None)
        assert_type(queries.extract_key(query), ListenerKey[CallbackQuery] | None)
        assert_type(messages.listeners, dict[ListenerKey[Message], ListenerModel[Message]])

    async def _check_listen_rejects(
        messages: MessageListener,
        queries: CallbackQueryListener,
        generic: UpdateListener[Message],
    ) -> None:
        await messages.listen(1)  # ty: ignore[invalid-argument-type]
        await messages.listen(MessageKey(1), None)  # ty: ignore[too-many-positional-arguments]
        await queries.listen(MessageKey(1))  # ty: ignore[invalid-argument-type]
        await messages.listen(MessageKey(1), strict="yes")  # ty: ignore[invalid-argument-type]
        await generic.listen(CallbackQueryKey(1))  # ty: ignore[invalid-argument-type]

    def _check_listener_bound() -> None:
        UpdateListener[int]  # ty: ignore[invalid-type-arguments]
