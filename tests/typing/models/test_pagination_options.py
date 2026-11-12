"""Static type tests for `pyroflow.models.pagination_options`."""

from __future__ import annotations as _annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pyroflow.models import (
        ArrowBarTexts,
        BarStyle,
        ItemCount,
        NumberedBarTexts,
        PageArrangement,
        SlidingBar,
    )

    def _check_options() -> None:
        PageArrangement(layout=[1, 2], repeat=True, per_page=4)
        PageArrangement(columns="1")  # ty: ignore[invalid-argument-type]
        BarStyle(nav="red")  # ty: ignore[invalid-argument-type]
        NumberedBarTexts(first=1)  # ty: ignore[invalid-argument-type]
        ArrowBarTexts(counter=None)
        ArrowBarTexts(back=None)  # ty: ignore[invalid-argument-type]
        SlidingBar(size=4, page="{page}", current="[{page}]")
        SlidingBar(size="4")  # ty: ignore[invalid-argument-type]
        ItemCount(3, strict=False)
        ItemCount("3")  # ty: ignore[invalid-argument-type]
