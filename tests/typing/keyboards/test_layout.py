"""Static type tests for ``pyroflow.keyboards.layout``."""

from __future__ import annotations as _annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing_extensions import assert_type

    from pyrogram.types import InlineKeyboardButton

    from pyroflow.keyboards import arrange

    def _check_arrange(button: InlineKeyboardButton) -> None:
        assert_type(arrange([button], columns=2), list[list[InlineKeyboardButton]])
        arrange([button], columns="2")  # ty: ignore[invalid-argument-type]
