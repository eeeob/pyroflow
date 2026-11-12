"""Static type tests for ``pyroflow.keyboards.pagination``."""

from __future__ import annotations as _annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing_extensions import assert_type

    from pyrogram.types import InlineKeyboardButton

    from pyroflow.keyboards import ArrowPagination, NumberedPagination, SlidingPagination
    from pyroflow.models import (
        ArrowBarTexts,
        ItemCount,
        NumberedBarTexts,
        Page,
        PageArrangement,
        SlidingBar,
    )

    def _button(n: int) -> InlineKeyboardButton:
        return InlineKeyboardButton(str(n), callback_data=str(n))

    def _fetch(offset: int, limit: int) -> list[int]:
        return [offset, limit]

    async def _fetch_async(offset: int, limit: int) -> list[int]:
        return [offset, limit]

    async def _check_numbered(button: InlineKeyboardButton) -> None:
        pages = NumberedPagination(
            [1, 2],
            item=_button,
            texts=NumberedBarTexts(first="{page}"),
            header=[[button]],
            footer=[[button]],
        )
        assert_type(pages, NumberedPagination[int])
        assert_type(await pages.build(2), Page[int])
        PageArrangement(lines="1")  # ty: ignore[invalid-argument-type]
        NumberedPagination([1, 2], item=_button, texts=ArrowBarTexts())  # ty: ignore[invalid-argument-type]
        NumberedPagination([1, 2], item=str)  # ty: ignore[invalid-argument-type]
        NumberedPagination(_fetch, item=_button, count=ItemCount(2))
        NumberedPagination(_fetch, item=_button, count=2)  # ty: ignore[invalid-argument-type]

    async def _check_sliding() -> None:
        pages = SlidingPagination([1, 2], item=_button, bar=SlidingBar(size=4))
        assert_type(pages, SlidingPagination[int])
        assert_type(await pages.build(2), Page[int])
        SlidingPagination([1, 2], item=_button, bar=ArrowBarTexts())  # ty: ignore[invalid-argument-type]

    async def _check_arrow() -> None:
        pages: ArrowPagination[int] = ArrowPagination(
            _fetch, item=_button, texts=ArrowBarTexts(counter="{page}")
        )
        assert_type(await pages.build(), Page[int])
        ArrowPagination[int](_fetch_async, item=_button)
        ArrowBarTexts(counter=1)  # ty: ignore[invalid-argument-type]
