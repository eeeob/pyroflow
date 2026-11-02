"""Static type tests for ``pyroflow.filters``."""

from __future__ import annotations as _annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from enum import Enum

    from pyrogram.filters import Filter
    from typing_extensions import assert_type

    from pyroflow import filters

    class _Action(Enum):
        BAN = "ban"

    def _is_digit(part: str) -> bool:
        return part.isdigit()

    async def _is_digit_async(part: str) -> bool:
        return part.isdigit()

    def _check_factories() -> None:
        assert_type(filters.startswith("a", ["b", ("c",)]), Filter)
        assert_type(filters.endswith("a"), Filter)
        assert_type(filters.equal("a", {"b"}), Filter)
        assert_type(filters.startswith(b"a", ["b", (b"c",)]), Filter)
        assert_type(filters.endswith(b"a"), Filter)
        assert_type(filters.equal(b"a", {"b"}), Filter)
        assert_type(filters.split_text("/ban"), Filter)
        assert_type(
            filters.split_text(_Action, _is_digit, _is_digit_async, strip=True, separator=" "),
            Filter,
        )
