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
        PageArrangement(columns="1")  # ty: ignore[invalid-argument-type]  # `columns` must be an int
        BarStyle(nav="red")  # ty: ignore[invalid-argument-type]  # `nav` must be callable
        NumberedBarTexts(first=1)  # ty: ignore[invalid-argument-type]  # `first` must be a str
        ArrowBarTexts(counter=None)
        ArrowBarTexts(back=None)  # ty: ignore[invalid-argument-type]  # `back` must be a str
        SlidingBar(size=4, page="{page}", current="[{page}]")
        SlidingBar(size="4")  # ty: ignore[invalid-argument-type]  # `size` must be an int
        ItemCount(3, strict=False)
        ItemCount("3")  # ty: ignore[invalid-argument-type]  # the count must be an int or a function
