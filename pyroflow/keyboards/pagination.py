"""Paged inline keyboards: the `Pagination` base and its bars."""

from __future__ import annotations as _annotations

from abc import ABC, abstractmethod
from math import ceil
from typing import Generic, cast, TYPE_CHECKING

from pyrogram.types import DisabledButton, InlineKeyboardButton, InlineKeyboardMarkup
from pytrove.typings import _T

from ..models import (
    ArrowBarTexts,
    BarStyle,
    ItemCount,
    NumberedBarTexts,
    Page,
    PageArrangement,
    SlidingBar,
)
from ..utils.helpers import call_maybe_async
from .layout import arrange

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

    from pytrove.typings import MaybeCoroutineCallable

    from ..models import ItemCount


class Pagination(ABC, Generic[_T]):
    """A keyboard of one page of items, with a bar to move between pages.

    Subclass it and write `nav_row` for a bar of your own; `nav_button` builds
    its buttons. Items are arranged as in `arrange`.

    Args:
        items: Everything to page through, as a sequence that can be sliced,
            or a function called as `(offset, limit)`, sync (run in a thread)
            or async, that returns one batch.
        item: Builds the `InlineKeyboardButton` of an item.
        count: How many items there are, as an `ItemCount`. `None` uses the
            length of a sequence, and leaves the count of a function unknown.
        page_data: Builds the `callback_data` of the bar's button to a page.
        arrangement: How a page is counted and arranged; `None` for five rows
            of one button each.
        style: The functions that change the bar's buttons; `None` for none.
        header: Rows kept above the items on every page.
        footer: Rows kept under the bar on every page.
        first_if_empty: Whether a page that comes back empty shows the first page
            instead.

    Example:
        >>> import asyncio
        >>> class NextOnly(Pagination):
        ...     def nav_row(self, number, total_pages, has_next):
        ...         return [self.nav_button("More", number + 1, number, total_pages)] if has_next else []
        >>> def button(text):
        ...     return InlineKeyboardButton(text, callback_data=text)
        >>> pages = NextOnly(["a", "b", "c"], item=button, arrangement=PageArrangement(lines=2, columns=1))
        >>> page = asyncio.run(pages.build())
        >>> [[button.text for button in row] for row in page.markup.inline_keyboard]
        [['a'], ['b'], ['More']]
    """

    __slots__ = (
        "items",
        "item",
        "count",
        "page_data",
        "arrangement",
        "style",
        "header",
        "footer",
        "first_if_empty",
    )

    def __init__(
        self,
        items: Sequence[_T] | MaybeCoroutineCallable[[int, int], Sequence[_T]],
        *,
        item: Callable[[_T], InlineKeyboardButton],
        count: ItemCount | None = None,
        page_data: Callable[[int], str] = str,
        arrangement: PageArrangement | None = None,
        style: BarStyle | None = None,
        header: Sequence[list[InlineKeyboardButton]] = (),
        footer: Sequence[list[InlineKeyboardButton]] = (),
        first_if_empty: bool = True,
    ) -> None:
        """Keep the items and the look of the keyboard; see the class docstring."""
        self.items = items
        """Everything to page through, or the function that fetches a batch."""
        self.item = item
        """Builds the button of an item."""
        self.count = count
        """How many items there are; `None` for the length, or an unknown count."""
        self.page_data = page_data
        """Builds the `callback_data` of the bar's button to a page."""
        self.arrangement = arrangement or PageArrangement(lines=5, columns=1)
        """How a page is counted and arranged."""
        self.style = style or BarStyle()
        """The functions that change the bar's buttons."""
        self.header = tuple(list(row) for row in header)
        """Rows kept above the items on every page."""
        self.footer = tuple(list(row) for row in footer)
        """Rows kept under the bar on every page."""
        self.first_if_empty = first_if_empty
        """Whether a page that comes back empty shows the first page instead."""

    @abstractmethod
    def nav_row(
        self, number: int, total_pages: int | None, has_next: bool
    ) -> list[InlineKeyboardButton]:
        """Build the bar of a page; called only for a page that gets a bar.

        Args:
            number: The current page.
            total_pages: How many pages there are; `None` when the count is
                unknown.
            has_next: Whether a page comes after this one.

        Returns:
            The bar's buttons.
        """

    def nav_button(
        self, label: str, target: int, number: int, total_pages: int | None
    ) -> InlineKeyboardButton:
        """Build the bar's button to `target`, disabled when that is the current page.

        Args:
            label: The text, with `{page}` and `{pages}` still to fill.
            target: The page the button leads to.
            number: The current page.
            total_pages: How many pages there are, or `None`.

        Returns:
            The button.
        """
        current = target == number
        button = InlineKeyboardButton(
            label.format(page=target, pages=total_pages),
            callback_data=self.page_data(target),
            disabled=DisabledButton() if current else None,
        )
        change = self.style.current if current else self.style.nav

        if change is not None:
            change(button)

        return button

    async def build(self, number: int = 1) -> Page[_T]:
        """Build a page, fetching only what it needs.

        With a known count, a page out of range becomes the nearest one. With
        an unknown count, one item more than a page is fetched to tell whether
        another page follows. A page that comes back empty shows the first
        page, or with `first_if_empty` off stays empty, with its bar to go
        back. A bar shows when there is another page to go to.

        Args:
            number: The page, from 1.

        Returns:
            The page, with its keyboard: the header, the items, the bar, and the footer.
        """
        if self.count is not None:
            value = self.count.value
            total = max(await call_maybe_async(value), 0) if callable(value) else value
        elif callable(self.items):
            total = None
        else:
            total = len(self.items)

        per_page = cast("int", self.arrangement.per_page)  # Its `__post_init__` filled it in.

        if total is None:
            number = max(number, 1)
            total_pages = None
            limit = per_page
            fetched = await self._fetch((number - 1) * per_page, limit + 1)
            has_next = len(fetched) > per_page
            has_bar = number > 1 or has_next
        else:
            total_pages = ceil(total / per_page)
            number = max(1, min(number, total_pages))
            offset = (number - 1) * per_page
            strict = self.count is not None and self.count.strict
            limit = min(per_page, total - offset) if strict else per_page
            fetched = await self._fetch(offset, limit) if limit else ()
            has_next = number < total_pages
            has_bar = total_pages > 1

        items = fetched[:limit]

        if self.first_if_empty and not items and number > 1:
            # The source shrank or its count is stale, so this page no longer exists.
            return await self.build(number=1)

        keyboard = arrange(
            [self.item(item) for item in items],
            columns=self.arrangement.columns,
            layout=self.arrangement.layout,
            repeat=self.arrangement.repeat,
        )

        if has_bar and (bar := self.nav_row(number, total_pages, has_next)):
            keyboard.append(bar)

        markup = InlineKeyboardMarkup([*self.header, *keyboard, *self.footer])

        return Page(number, items, total_pages, has_next, markup)

    async def _fetch(self, offset: int, limit: int) -> Sequence[_T]:
        """Return up to `limit` items from `offset`.

        Args:
            offset: How many items come before the first one.
            limit: How many items to return at most, if the source obeys.

        Returns:
            The items.
        """
        if callable(self.items):
            return await call_maybe_async(self.items, offset, limit)

        return self.items[offset : offset + limit]


class NumberedPagination(Pagination[_T]):
    """A `Pagination` whose bar shows the first, near and last pages by number.

    It needs the number of pages, so a fetch function must come with `count`.

    Args:
        items: As in `Pagination`.
        item: As in `Pagination`.
        texts: The bar's texts; `None` for the defaults of `NumberedBarTexts`.
        count: As in `Pagination`.
        page_data: As in `Pagination`.
        arrangement: As in `Pagination`.
        style: As in `Pagination`.
        header: As in `Pagination`.
        footer: As in `Pagination`.
        first_if_empty: As in `Pagination`.

    Raises:
        TypeError: If `items` is a function and `count` is `None`.

    Example:
        >>> import asyncio
        >>> def button(n):
        ...     return InlineKeyboardButton(str(n), callback_data=f"item:{n}")
        >>> pages = NumberedPagination(
        ...     range(1, 8), item=button, arrangement=PageArrangement(lines=2, columns=1)
        ... )
        >>> page = asyncio.run(pages.build(2))
        >>> [[button.text for button in row] for row in page.markup.inline_keyboard]
        [['3'], ['4'], ['« 1', '· 2 ·', '3 ›', '4 »']]
    """

    __slots__ = ("texts",)

    def __init__(
        self,
        items: Sequence[_T] | MaybeCoroutineCallable[[int, int], Sequence[_T]],
        *,
        item: Callable[[_T], InlineKeyboardButton],
        texts: NumberedBarTexts | None = None,
        count: ItemCount | None = None,
        page_data: Callable[[int], str] = str,
        arrangement: PageArrangement | None = None,
        style: BarStyle | None = None,
        header: Sequence[list[InlineKeyboardButton]] = (),
        footer: Sequence[list[InlineKeyboardButton]] = (),
        first_if_empty: bool = True,
    ) -> None:
        """Keep the bar's texts and the rest; see the class docstring."""
        if callable(items) and count is None:
            msg = "NumberedPagination needs the count of a fetch function"
            raise TypeError(msg)

        super().__init__(
            items,
            item=item,
            count=count,
            page_data=page_data,
            arrangement=arrangement,
            style=style,
            header=header,
            footer=footer,
            first_if_empty=first_if_empty,
        )
        self.texts = texts or NumberedBarTexts()
        """The texts of the bar."""

    def nav_row(
        self, number: int, total_pages: int | None, has_next: bool
    ) -> list[InlineKeyboardButton]:
        """Build the bar of a page; see `Pagination.nav_row`.

        Args:
            number: The current page.
            total_pages: How many pages there are.
            has_next: Unused; the numbers tell.

        Returns:
            The bar's buttons, each page at most once, in page order.
        """
        pages = cast("int", total_pages)  # The constructor refuses an unknown count.
        row = []

        for target in sorted({1, max(number - 1, 1), number, min(number + 1, pages), pages}):
            if target == number:
                label = self.texts.current
            elif target == 1:
                label = self.texts.first
            elif target == pages:
                label = self.texts.last
            else:
                label = self.texts.previous if target < number else self.texts.next

            row.append(self.nav_button(label, target, number, pages))

        return row


class ArrowPagination(Pagination[_T]):
    """A `Pagination` whose bar flips with arrows, and works without a count.

    Args:
        items: As in `Pagination`.
        item: As in `Pagination`.
        texts: The bar's texts; `None` for the defaults of `ArrowBarTexts`.
        count: As in `Pagination`.
        page_data: As in `Pagination`.
        arrangement: As in `Pagination`.
        style: As in `Pagination`.
        header: As in `Pagination`.
        footer: As in `Pagination`.
        first_if_empty: As in `Pagination`.

    Example:
        >>> import asyncio
        >>> def fetch(offset, limit):
        ...     return list(range(7))[offset : offset + limit]
        >>> def button(n):
        ...     return InlineKeyboardButton(str(n), callback_data=str(n))
        >>> pages = ArrowPagination(
        ...     fetch,
        ...     item=button,
        ...     arrangement=PageArrangement(lines=3, columns=1),
        ...     texts=ArrowBarTexts(counter="{page}/{pages}"),
        ... )
        >>> page = asyncio.run(pages.build(2))
        >>> page.total_pages, page.has_next, [button.text for button in page.markup.inline_keyboard[-1]]
        (None, True, ['‹', '2', '›'])
    """

    __slots__ = ("texts",)

    def __init__(
        self,
        items: Sequence[_T] | MaybeCoroutineCallable[[int, int], Sequence[_T]],
        *,
        item: Callable[[_T], InlineKeyboardButton],
        texts: ArrowBarTexts | None = None,
        count: ItemCount | None = None,
        page_data: Callable[[int], str] = str,
        arrangement: PageArrangement | None = None,
        style: BarStyle | None = None,
        header: Sequence[list[InlineKeyboardButton]] = (),
        footer: Sequence[list[InlineKeyboardButton]] = (),
        first_if_empty: bool = True,
    ) -> None:
        """Keep the bar's texts and the rest; see the class docstring."""
        super().__init__(
            items,
            item=item,
            count=count,
            page_data=page_data,
            arrangement=arrangement,
            style=style,
            header=header,
            footer=footer,
            first_if_empty=first_if_empty,
        )
        self.texts = texts or ArrowBarTexts()
        """The texts of the bar."""

    def nav_row(
        self, number: int, total_pages: int | None, has_next: bool
    ) -> list[InlineKeyboardButton]:
        """Build the bar of a page; see `Pagination.nav_row`.

        Args:
            number: The current page.
            total_pages: How many pages there are; `None` when the count is
                unknown.
            has_next: Whether a page comes after this one.

        Returns:
            The back arrow, the counter and the forward arrow, those that apply.
        """
        row = []

        if number > 1:
            row.append(self.nav_button(self.texts.back, number - 1, number, total_pages))

        if self.texts.counter is not None:
            label = self.texts.unknown_counter if total_pages is None else self.texts.counter
            row.append(self.nav_button(label, number, number, total_pages))

        if has_next:
            row.append(self.nav_button(self.texts.forward, number + 1, number, total_pages))

        return row


class SlidingPagination(Pagination[_T]):
    """A `Pagination` whose bar shows every page by number, as far as they fit.

    The bar shows at most `SlidingBar.size` numbers, in fixed groups. Reaching
    the last number of a group brings the next group, which starts one number
    before it so that the way back stays shown. It needs the number of pages,
    so a fetch function must come with `count`.

    Args:
        items: As in `Pagination`.
        item: As in `Pagination`.
        bar: The bar's size and texts; `None` for the defaults of `SlidingBar`.
        count: As in `Pagination`.
        page_data: As in `Pagination`.
        arrangement: As in `Pagination`.
        style: As in `Pagination`.
        header: As in `Pagination`.
        footer: As in `Pagination`.
        first_if_empty: As in `Pagination`.

    Raises:
        TypeError: If `items` is a function and `count` is `None`.

    Example:
        >>> import asyncio
        >>> def button(n):
        ...     return InlineKeyboardButton(str(n), callback_data=str(n))
        >>> pages = SlidingPagination(
        ...     range(1, 21), item=button, arrangement=PageArrangement(lines=2, columns=1), bar=SlidingBar(size=4)
        ... )
        >>> page = asyncio.run(pages.build(4))
        >>> [[button.text for button in row] for row in page.markup.inline_keyboard]
        [['7'], ['8'], ['3', '· 4 ·', '5', '6']]
    """

    __slots__ = ("bar",)

    def __init__(
        self,
        items: Sequence[_T] | MaybeCoroutineCallable[[int, int], Sequence[_T]],
        *,
        item: Callable[[_T], InlineKeyboardButton],
        bar: SlidingBar | None = None,
        count: ItemCount | None = None,
        page_data: Callable[[int], str] = str,
        arrangement: PageArrangement | None = None,
        style: BarStyle | None = None,
        header: Sequence[list[InlineKeyboardButton]] = (),
        footer: Sequence[list[InlineKeyboardButton]] = (),
        first_if_empty: bool = True,
    ) -> None:
        """Keep the bar's options and the rest; see the class docstring."""
        if callable(items) and count is None:
            msg = "SlidingPagination needs the count of a fetch function"
            raise TypeError(msg)

        super().__init__(
            items,
            item=item,
            count=count,
            page_data=page_data,
            arrangement=arrangement,
            style=style,
            header=header,
            footer=footer,
            first_if_empty=first_if_empty,
        )
        self.bar = bar or SlidingBar()
        """The size and texts of the bar."""

    def nav_row(
        self, number: int, total_pages: int | None, has_next: bool
    ) -> list[InlineKeyboardButton]:
        """Build the bar of a page; see `Pagination.nav_row`.

        Args:
            number: The current page.
            total_pages: How many pages there are.
            has_next: Unused; the numbers tell.

        Returns:
            The numbers of the current page's group, which always include
            the pages on both sides of it.
        """
        pages = cast("int", total_pages)  # The constructor refuses an unknown count.
        size = self.bar.size
        # Each group shares two numbers with the next, so the way back stays shown.
        step = size - 2
        # The last page has nothing after it, so it stays in the group of the page before.
        first = 1 + max(min(number, pages - 1) - 2, 0) // step * step

        return [
            self.nav_button(
                self.bar.current if target == number else self.bar.page, target, number, pages
            )
            for target in range(first, min(first + size, pages + 1))
        ]


__all__ = (
    "Pagination",
    "NumberedPagination",
    "ArrowPagination",
    "SlidingPagination",
)
