"""Static type tests for `pyroflow.models.listener_key`."""

from __future__ import annotations as _annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing_extensions import assert_type

    from pyroflow.models import CallbackQueryKey, ListenerKey, MessageKey
    from pyroflow.types import CallbackQuery, Message

    def _check_keys(message: Message, query: CallbackQuery, key: MessageKey) -> None:
        assert_type(ListenerKey.key_fields, tuple[str, ...])
        assert_type(key.exact_fields, tuple[str, ...])
        assert_type(key.to_tuple(), tuple[object, ...])
        assert_type(key.to_dict(), dict[str, object])
        assert_type(MessageKey.from_update(message), MessageKey | None)
        assert_type(MessageKey.from_sent(message, 2), MessageKey)
        assert_type(CallbackQueryKey.from_update(query), CallbackQueryKey | None)
        assert_type(CallbackQueryKey.from_sent(message), CallbackQueryKey)
        assert_type(key.user_id, int | None)
        assert_type(key.ephemeral, bool)
        MessageKey(user_id="2")  # ty: ignore[invalid-argument-type]
        CallbackQueryKey(message_thread_id=3)  # ty: ignore[unknown-argument]
