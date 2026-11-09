"""The options of a `pyroflow.keyboards.Pagination`: its arrangement, item count, bar styling and texts."""

from __future__ import annotations as _annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from itertools import cycle, islice

from pyrogram.types import InlineKeyboardButton
from pytrove.typings import MaybeCoroutineCallable


@dataclass(frozen=True, slots=True)
class PageArrangement:
    """How many items a page holds and how they are arranged, as in `arrange`.

    Pass one of these sets, and nothing else; any other mix raises `ValueError`:

    | Options                        | `per_page`          | Rows                      |
    |--------------------------------|---------------------|---------------------------|
    | `lines`, `columns`             | `lines * columns`   | `lines` rows of `columns` |
    | `per_page`, `columns`          | `per_page`          | rows of `columns`         |
    | `layout`                       | sum of `layout`     | one row per size          |
    | `layout`, `per_page`           | `per_page` >= sum   | the last size goes on     |
    | `layout`, `repeat`, `lines`    | first `lines` sizes | `lines` rows, cycling     |
    | `layout`, `repeat`, `per_page` | `per_page`          | the sizes cycling         |

    Example:
        >>> PageArrangement(lines=4, columns=3)
        PageArrangement(lines=4, columns=3, layout=None, repeat=False, per_page=12)
        >>> PageArrangement(layout=[1, 2]).per_page
        3
    """

    lines: int | None = None
    """Rows of items on a page."""
    columns: int | None = None
    """Buttons per row."""
    layout: Sequence[int] | None = None
    """Row sizes."""
    repeat: bool = False
    """Whether `layout` starts over after its last size."""
    per_page: int | None = None
    """Items on a page; worked out from the rest when not passed."""

    def __post_init__(self) -> None:
        """Refuse anything but the documented sets, then fill in `per_page`.

        Raises:
            ValueError: If `lines`, `per_page`, `columns` or a size of `layout`
                is not positive, or the values are not one of the sets in the
                class docstring.
        """
        lines, columns, layout, per_page = self.lines, self.columns, self.layout, self.per_page

        if any(value is not None and value <= 0 for value in (lines, columns, per_page)) or (
            layout is not None and (not layout or min(layout) <= 0)
        ):
            msg = "lines, per_page, columns and layout sizes must be positive"
            raise ValueError(msg)

        if columns is not None and layout is not None:
            msg = "Pass columns or layout, not both"
            raise ValueError(msg)

        if lines is not None and per_page is not None:
            msg = "Pass lines or per_page, not both"
            raise ValueError(msg)

        if lines is not None and layout is not None and not self.repeat:
            msg = "lines needs repeat when layout is given"
            raise ValueError(msg)

        if self.repeat and layout is None:
            msg = "repeat needs layout"
            raise ValueError(msg)

        if columns is None and layout is None:
            msg = "Pass columns or layout"
            raise ValueError(msg)

        if (
            layout is not None
            and per_page is not None
            and not self.repeat
            and per_page < sum(layout)
        ):
            msg = "per_page cannot be less than the sum of layout"
            raise ValueError(msg)

        if per_page is not None:
            pass
        elif columns is not None and lines is not None:
            per_page = lines * columns
        elif layout is not None and not self.repeat:
            per_page = sum(layout)
        elif layout is not None and lines is not None:
            per_page = sum(islice(cycle(layout), lines))
        else:
            msg = "Pass lines or per_page with columns or repeat"
            raise ValueError(msg)

        object.__setattr__(self, "per_page", per_page)


@dataclass(frozen=True, slots=True)
class BarStyle:
    """Functions that change the bar's buttons of a `Pagination`, once each is built.

    A function changes the button it gets, such as its `style`, and what it
    returns is ignored. It is called as it is, so an `async def` one never runs.

    Example:
        >>> BarStyle(nav=print).current is None
        True
    """

    nav: Callable[[InlineKeyboardButton], object] | None = None
    """Called with each button to another page; `None` for none."""
    current: Callable[[InlineKeyboardButton], object] | None = None
    """Called with the current page's button; `None` for none."""


@dataclass(frozen=True, slots=True)
class NumberedBarTexts:
    """The texts of the bar of a `NumberedPagination`, with `{page}` and `{pages}`.

    Example:
        >>> NumberedBarTexts(first="<<").last
        '{page} »'
    """

    first: str = "« {page}"
    """The first page."""
    previous: str = "‹ {page}"
    """The page before the current one."""
    current: str = "· {page} ·"
    """The current page."""
    next: str = "{page} ›"
    """The page after the current one."""
    last: str = "{page} »"
    """The last page."""


@dataclass(frozen=True, slots=True)
class ArrowBarTexts:
    """The texts of the bar of an `ArrowPagination`, with `{page}` and `{pages}`.

    Example:
        >>> ArrowBarTexts(counter="{page}/{pages}").back
        '‹'
    """

    back: str = "‹"
    """The arrow to the previous page."""
    forward: str = "›"
    """The arrow to the next page."""
    counter: str | None = None
    """The current page's button between the arrows; `None` for none."""
    unknown_counter: str = "{page}"
    """`counter` when the count is unknown, with `{page}`."""


@dataclass(frozen=True, slots=True)
class SlidingBar:
    """The size and texts of the bar of a `SlidingPagination`, with `{page}` and `{pages}`.

    Example:
        >>> SlidingBar(size=4).current
        '· {page} ·'
    """

    size: int = 8
    """The most page numbers shown at once."""
    page: str = "{page}"
    """Any page but the current one."""
    current: str = "· {page} ·"
    """The current page."""

    def __post_init__(self) -> None:
        """Check `size`, which must hold the current page and one on each side.

        Raises:
            ValueError: If `size` is less than 3.
        """
        if self.size < 3:
            msg = "size must be at least 3"
            raise ValueError(msg)


@dataclass(frozen=True, slots=True)
class ItemCount:
    """How many items a `Pagination` has, and how strictly that number is kept.

    A function is read again on every build. With `strict`, no item past `value`
    is fetched or shown. Without it, `value` only sets how many pages there are,
    and each page is fetched whole.

    Example:
        >>> ItemCount(13).strict
        True
    """

    value: int | MaybeCoroutineCallable[[], int]
    """The number of items, or a sync or async function that returns it."""
    strict: bool = True
    """Whether no item past `value` is fetched or shown."""

    def __post_init__(self) -> None:
        """Refuse a negative number.

        Raises:
            ValueError: If `value` is a number below zero.
        """
        value = self.value

        if not callable(value) and value < 0:
            msg = "value must not be negative"
            raise ValueError(msg)


__all__ = (
    "PageArrangement",
    "ItemCount",
    "BarStyle",
    "NumberedBarTexts",
    "ArrowBarTexts",
    "SlidingBar",
)
