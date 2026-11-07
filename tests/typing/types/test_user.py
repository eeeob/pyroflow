"""Static type tests for `pyroflow.types.user`."""

from __future__ import annotations as _annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing_extensions import assert_type

    from pyroflow.types import Message, User

    def _check_messages_are_the_patched_class(user: User) -> None:
        assert_type(user.pinned_message, Message | None)
        assert_type(user.personal_channel_message, Message | None)
