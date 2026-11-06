"""Static type tests for ``pyroflow.filters``."""

from __future__ import annotations as _annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import re
    from enum import Enum

    from pyrogram.filters import Filter
    from pyrogram.types import BotCommandScope, BotCommandScopeChat
    from typing_extensions import assert_type

    from pyroflow import filters
    from pyroflow.enums import CommandUsernamePolicy

    class _Action(Enum):
        BAN = "ban"

    def _is_digit(part: str) -> bool:
        return part.isdigit()

    async def _is_digit_async(part: str) -> bool:
        return part.isdigit()

    def _check_registered_command() -> None:
        flt = filters.registered_command(ephemeral=False)
        assert_type(filters.registered_command(), filters.registered_command)
        assert_type(flt.ephemeral, bool)
        assert_type(flt.username_policy, CommandUsernamePolicy | None)
        assert_type(flt.scopes, tuple[BotCommandScope, ...])
        assert_type(filters.registered_command.DEFAULT_SCOPES, tuple[BotCommandScope, ...])
        assert_type(flt.language_codes, tuple[str, ...])
        filters.registered_command(scopes=[BotCommandScopeChat(1)], language_codes={"ar"})
        _as_filter: Filter = flt
        filters.registered_command(False)  # ty: ignore[too-many-positional-arguments]
        filters.registered_command(ephemeral="no")  # ty: ignore[invalid-argument-type]
        filters.registered_command(username_policy="any")  # ty: ignore[invalid-argument-type]
        filters.registered_command(scopes=["default"])  # ty: ignore[invalid-argument-type]
        filters.registered_command(language_codes=[1])  # ty: ignore[invalid-argument-type]

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
        assert_type(
            filters.split_text("/ban", re.compile(r"\d+"), separator=" "),
            Filter,
        )
