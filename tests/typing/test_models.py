"""Static type tests for ``pyroflow.models``."""

from __future__ import annotations as _annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Generator

    from typing_extensions import assert_type

    from pyroflow.models import ListenerKey

    def _check_listener_key(key: ListenerKey) -> None:
        assert_type(ListenerKey(1), ListenerKey)
        assert_type(ListenerKey(1, 2), ListenerKey)
        assert_type(ListenerKey(chat_id=1, user_id=None, message_id=3), ListenerKey)
        assert_type(key.chat_id, int)
        assert_type(key.user_id, int | None)
        assert_type(key.message_id, int | None)
        assert_type(key.to_tuple, tuple[int, int | None, int | None])
        assert_type(key.sub_keys(), Generator[ListenerKey, None, None])

    def _check_listener_key_rejects(key: ListenerKey) -> None:
        ListenerKey()  # ty: ignore[missing-argument]
        ListenerKey("1")  # ty: ignore[invalid-argument-type]
        ListenerKey(1, "2")  # ty: ignore[invalid-argument-type]
        key.chat_id = 2  # ty: ignore[invalid-assignment]


def test_type_checks_are_not_defined_at_runtime() -> None:
    assert "_check_listener_key" not in globals()
