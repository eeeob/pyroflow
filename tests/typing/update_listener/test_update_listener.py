"""Static type tests for ``pyroflow.update_listener.update_listener``."""

from __future__ import annotations as _annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing_extensions import assert_type

    from pyroflow.models import CallbackQueryKey, ListenerContext, ListenerModel, MessageKey
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
        generic: UpdateListener[Message, MessageKey],
    ) -> None:
        assert_type(await messages.listen(), Message)
        assert_type(
            await messages.listen(
                chat_id=1,
                user_id=2,
                message_thread_id=3,
                direct_messages_topic_id=4,
                ephemeral=True,
                context=ListenerContext(k=1),
                timeout=1.5,
            ),
            Message,
        )
        assert_type(await messages.listen(1, 2, 3, 4, True), Message)
        assert_type(await messages(chat_id=1), Message)
        assert_type(await queries.listen(chat_id=1), CallbackQuery)
        assert_type(await queries(chat_id=1, message_id=3, strict=True), CallbackQuery)
        assert_type(await generic.listen(MessageKey(1)), Message)

    def _check_keys(
        messages: MessageListener,
        queries: CallbackQueryListener,
        message: Message,
        query: CallbackQuery,
    ) -> None:
        assert_type(messages.extract_key(message), MessageKey | None)
        assert_type(queries.extract_key(query), CallbackQueryKey | None)
        assert_type(messages.listeners, dict[MessageKey, ListenerModel[MessageKey]])

    async def _check_listen_rejects(
        messages: MessageListener,
        queries: CallbackQueryListener,
        generic: UpdateListener[Message, MessageKey],
    ) -> None:
        await messages.listen(chat_id="1")  # ty: ignore[invalid-argument-type]
        await messages.listen(1, 2, 3, 4, True, None)  # ty: ignore[too-many-positional-arguments]
        await queries.listen(message_id="3")  # ty: ignore[invalid-argument-type]
        await messages.listen(chat_id=1, strict="yes")  # ty: ignore[invalid-argument-type]
        await generic.listen(CallbackQueryKey(1))  # ty: ignore[invalid-argument-type]

    def _check_listener_bound() -> None:
        UpdateListener[int, MessageKey]  # ty: ignore[invalid-type-arguments]
        UpdateListener[Message, int]  # ty: ignore[invalid-type-arguments]
