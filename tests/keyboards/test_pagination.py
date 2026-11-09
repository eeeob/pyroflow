"""Tests for `pyroflow.keyboards.pagination`: the base and its bars."""

from __future__ import annotations as _annotations

from typing import Any, TYPE_CHECKING
from unittest.mock import Mock

import pytest
from pyrogram.enums import ButtonStyle
from pyrogram.types import DisabledButton, InlineKeyboardButton

from pyroflow.keyboards import ArrowPagination, NumberedPagination, Pagination, SlidingPagination
from pyroflow.keyboards import pagination as module
from pyroflow.models import (
    ArrowBarTexts,
    BarStyle,
    ItemCount,
    NumberedBarTexts,
    Page,
    PageArrangement,
    SlidingBar,
)

if TYPE_CHECKING:
    from collections.abc import Callable


def btn(text: str, value: str) -> InlineKeyboardButton:
    return InlineKeyboardButton(text, callback_data=value)


def paint(color: ButtonStyle) -> Callable[[InlineKeyboardButton], None]:
    def change(button: InlineKeyboardButton) -> None:
        button.style = color

    return change


def item_button(n: int) -> InlineKeyboardButton:
    return btn(f"i{n}", f"item:{n}")


def texts(rows: list[list[InlineKeyboardButton]]) -> list[list[str]]:
    return [[button.text for button in row] for row in rows]


def make_pages(count: int, **kw: Any) -> NumberedPagination[int]:
    return NumberedPagination(list(range(1, count + 1)), item=item_button, **kw)


def make_arrows(count: int, **kw: Any) -> ArrowPagination[int]:
    return ArrowPagination(list(range(1, count + 1)), item=item_button, **kw)


class Fetch:
    """A sync fetch function that records the arguments of each call."""

    def __init__(self, count: int, extra: int = 0) -> None:
        self.data = list(range(1, count + 1))
        self.extra = extra
        self.calls: list[tuple[int, int]] = []

    def __call__(self, offset: int, limit: int) -> list[int]:
        self.calls.append((offset, limit))
        return self.data[offset : offset + limit + self.extra]


async def rows_of(pages: Pagination[int], number: int = 1) -> list[list[InlineKeyboardButton]]:
    return (await pages.build(number)).markup.inline_keyboard


async def bar(pages: Pagination[int], number: int) -> list[str]:
    return [button.text for button in (await rows_of(pages, number))[-1]]


def test_module_all() -> None:
    assert module.__all__ == (
        "Pagination",
        "NumberedPagination",
        "ArrowPagination",
        "SlidingPagination",
    )


def test_pagination_is_generic_in_its_item_type() -> None:
    assert Pagination.__parameters__ == (module._T,)


def test_pagination_is_abstract() -> None:
    with pytest.raises(TypeError, match="abstract"):
        Pagination([1], item=item_button)


# --- the constructor --------------------------------------------------------


def test_pagination_keeps_what_it_is_given() -> None:
    def page_data(page: int) -> str:
        return f"p{page}"

    footer = [[btn("x", "x")]]
    arrangement = PageArrangement(lines=2, columns=3)
    style = BarStyle(nav=print)
    pages = NumberedPagination(
        [1],
        item=item_button,
        count=ItemCount(9, strict=False),
        page_data=page_data,
        arrangement=arrangement,
        style=style,
        footer=footer,
    )

    assert pages.items == [1]
    assert pages.item is item_button
    assert pages.count == ItemCount(9, strict=False)
    assert pages.page_data is page_data
    assert pages.arrangement is arrangement
    assert pages.style is style
    assert pages.arrangement.columns == 3
    assert pages.arrangement.per_page == 6
    assert pages.footer == tuple(footer)


def test_pagination_defaults() -> None:
    pages = make_pages(1)

    assert pages.page_data(3) == "3"
    assert pages.count is None
    assert pages.arrangement == PageArrangement(lines=5, columns=1)
    assert pages.style == BarStyle()
    assert pages.arrangement.per_page == 5
    assert pages.header == ()
    assert pages.footer == ()
    assert pages.first_if_empty is True


@pytest.mark.parametrize(
    ("kw", "expected"),
    [
        ({"lines": 2, "columns": 3}, 6),
        ({"layout": [1, 2]}, 3),
        ({"lines": 3, "layout": [1, 2], "repeat": True}, 4),
        ({"columns": 2, "per_page": 5}, 5),
    ],
)
async def test_per_page_is_worked_out_in_the_constructor(kw: dict[str, Any], expected: int) -> None:
    pages = make_pages(20, arrangement=PageArrangement(**kw))
    rows = (await rows_of(pages))[:-1]

    assert pages.arrangement.per_page == expected
    assert sum(len(row) for row in rows) == expected


def test_constructor_refuses_other_columns_with_layout() -> None:
    with pytest.raises(ValueError, match="not both"):
        make_pages(3, arrangement=PageArrangement(columns=2, layout=[1]))


@pytest.mark.parametrize(
    "kw",
    [
        {"lines": 0},
        {"lines": 0, "layout": [1]},
        {"per_page": 0},
        {"per_page": -1},
        {"columns": 0},
        {"layout": []},
        {"layout": [0]},
        {"layout": [0], "repeat": True},
        {"layout": [1, 0]},
        {"layout": [], "repeat": True},
    ],
)
def test_constructor_refuses_what_is_not_positive(kw: dict[str, Any]) -> None:
    with pytest.raises(ValueError, match="must be positive"):
        make_pages(3, arrangement=PageArrangement(**kw))


# --- build: a sequence ------------------------------------------------------


async def test_build_defaults_to_the_first_page_of_five_lines() -> None:
    assert texts((await rows_of(make_pages(6)))[:-1]) == [
        ["i1"],
        ["i2"],
        ["i3"],
        ["i4"],
        ["i5"],
    ]


async def test_build_returns_the_page() -> None:
    page = await make_pages(5, arrangement=PageArrangement(lines=2, columns=1)).build(2)

    assert isinstance(page, Page)
    assert page.number == 2
    assert page.items == [3, 4]
    assert page.total_pages == 3
    assert page.has_next is True


async def test_build_shows_the_items_of_the_page() -> None:
    assert texts(
        (await rows_of(make_pages(5, arrangement=PageArrangement(lines=2, columns=1)), 2))[:-1]
    ) == [
        ["i3"],
        ["i4"],
    ]


async def test_build_of_the_last_page_has_no_next() -> None:
    assert (
        await make_pages(5, arrangement=PageArrangement(lines=2, columns=1)).build(3)
    ).has_next is False


async def test_build_applies_count_to_a_sequence() -> None:
    page = await NumberedPagination(
        [1, 2, 3, 4, 5],
        item=item_button,
        arrangement=PageArrangement(lines=2, columns=1),
        count=ItemCount(3),
    ).build(2)

    assert (page.number, list(page.items), page.total_pages) == (2, [3], 2)


@pytest.mark.parametrize(
    ("number", "expected", "items"),
    [(99, 3, [["i5"]]), (0, 1, [["i1"], ["i2"]]), (-1, 1, [["i1"], ["i2"]])],
)
async def test_build_moves_a_page_out_of_range_to_the_nearest_one(
    number: int, expected: int, items: list[list[str]]
) -> None:
    page = await make_pages(5, arrangement=PageArrangement(lines=2, columns=1)).build(number)

    assert page.number == expected
    assert texts(page.markup.inline_keyboard[:-1]) == items


async def test_build_of_no_items_has_no_bar() -> None:
    page = await make_pages(0).build(3)

    assert page.markup.inline_keyboard == []
    assert (page.number, page.items, page.total_pages, page.has_next) == (1, [], 0, False)


async def test_build_of_a_single_page_has_no_bar() -> None:
    assert texts(await rows_of(make_pages(2, arrangement=PageArrangement(lines=2, columns=1)))) == [
        ["i1"],
        ["i2"],
    ]


@pytest.mark.parametrize("count", [0, 2, 5])
async def test_build_puts_the_footer_last_on_every_kind_of_page(count: int) -> None:
    pages = make_pages(
        count,
        arrangement=PageArrangement(lines=2, columns=1),
        footer=([btn("x", "x"), btn("y", "y")], [btn("z", "z")]),
    )

    assert texts((await rows_of(pages))[-2:]) == [["x", "y"], ["z"]]


async def test_build_arranges_the_items_like_ikb() -> None:
    assert texts(await rows_of(make_pages(3, arrangement=PageArrangement(layout=[2, 1])))) == [
        ["i1", "i2"],
        ["i3"],
    ]


async def test_build_uses_the_button_item_returns_as_it_is() -> None:
    button = btn("t", "v")

    assert (await rows_of(NumberedPagination([1], item=lambda _: button)))[0][0] is button


# --- build: a fetch function with a count -----------------------------------


async def test_fetch_gets_the_offset_and_limit_of_the_page() -> None:
    fetch = Fetch(7)
    page = await NumberedPagination(
        fetch,
        item=item_button,
        count=ItemCount(7, strict=False),
        arrangement=PageArrangement(lines=2, columns=1),
    ).build(2)

    assert fetch.calls == [(2, 2)]
    assert page.items == [3, 4]
    assert (page.total_pages, page.has_next) == (4, True)


async def test_async_fetch_is_awaited() -> None:
    data = list(range(1, 8))

    async def fetch(offset: int, limit: int) -> list[int]:
        return data[offset : offset + limit]

    page = await NumberedPagination(
        fetch,
        item=item_button,
        count=ItemCount(7, strict=False),
        arrangement=PageArrangement(lines=2, columns=1),
    ).build(4)

    assert page.items == [7]
    assert page.has_next is False


async def test_count_as_a_sync_function() -> None:
    pages = NumberedPagination(
        Fetch(7),
        item=item_button,
        count=ItemCount(lambda: 7, strict=False),
        arrangement=PageArrangement(lines=2, columns=1),
    )

    assert (await pages.build()).total_pages == 4


async def test_count_as_an_async_function() -> None:
    async def count() -> int:
        return 7

    pages = NumberedPagination(
        Fetch(7),
        item=item_button,
        count=ItemCount(count, strict=False),
        arrangement=PageArrangement(lines=2, columns=1),
    )

    assert (await pages.build()).total_pages == 4


async def test_count_is_asked_on_every_build() -> None:
    answers = iter([3, 9])
    pages = NumberedPagination(
        Fetch(9),
        item=item_button,
        count=ItemCount(lambda: next(answers), strict=False),
        arrangement=PageArrangement(lines=2, columns=1),
    )

    assert (await pages.build()).total_pages == 2
    assert (await pages.build()).total_pages == 5


async def test_fetch_is_clamped_by_the_count() -> None:
    fetch = Fetch(7)
    page = await NumberedPagination(
        fetch,
        item=item_button,
        count=ItemCount(7, strict=False),
        arrangement=PageArrangement(lines=2, columns=1),
    ).build(99)

    assert page.number == 4
    assert fetch.calls == [(6, 2)]


async def test_a_fetch_that_returns_too_much_is_cut_to_the_page() -> None:
    page = await NumberedPagination(
        Fetch(7, extra=3),
        item=item_button,
        count=ItemCount(7, strict=False),
        arrangement=PageArrangement(lines=2, columns=1),
    ).build()

    assert page.items == [1, 2]


async def test_a_known_empty_count() -> None:
    page = await NumberedPagination(
        Fetch(0), item=item_button, count=ItemCount(0, strict=False), footer=[[btn("x", "x")]]
    ).build(5)

    assert (page.number, page.total_pages, page.has_next) == (1, 0, False)
    assert texts(page.markup.inline_keyboard) == [["x"]]


# --- build: an unknown count ------------------------------------------------


async def test_unknown_count_fetches_one_more_than_a_page() -> None:
    fetch = Fetch(7)
    page = await ArrowPagination(
        fetch, item=item_button, arrangement=PageArrangement(lines=2, columns=1)
    ).build(2)

    assert fetch.calls == [(2, 3)]
    assert page.items == [3, 4]
    assert (page.number, page.total_pages, page.has_next) == (2, None, True)


@pytest.mark.parametrize(("count", "has_next"), [(4, False), (5, True)])
async def test_unknown_count_detects_the_last_page(count: int, has_next: bool) -> None:
    assert (
        await ArrowPagination(
            Fetch(count), item=item_button, arrangement=PageArrangement(lines=2, columns=1)
        ).build(2)
    ).has_next is (has_next)


async def test_unknown_count_with_an_exactly_full_last_page_has_only_the_back_arrow() -> None:
    assert await bar(
        ArrowPagination(
            Fetch(4), item=item_button, arrangement=PageArrangement(lines=2, columns=1)
        ),
        2,
    ) == ["‹"]


@pytest.mark.parametrize("number", [0, -3])
async def test_unknown_count_moves_a_low_page_to_the_first(number: int) -> None:
    fetch = Fetch(7)
    page = await ArrowPagination(
        fetch, item=item_button, arrangement=PageArrangement(lines=2, columns=1)
    ).build(number)

    assert page.number == 1
    assert fetch.calls == [(0, 3)]


async def test_unknown_count_with_one_page_has_no_bar() -> None:
    assert texts(
        await rows_of(
            ArrowPagination(
                Fetch(2), item=item_button, arrangement=PageArrangement(lines=2, columns=1)
            )
        )
    ) == [
        ["i1"],
        ["i2"],
    ]


async def test_unknown_count_with_no_items_has_only_the_footer() -> None:
    page = await ArrowPagination(
        Fetch(0),
        item=item_button,
        arrangement=PageArrangement(lines=2, columns=1),
        footer=[[btn("x", "x")]],
    ).build(1)

    assert page.items == []
    assert page.has_next is False
    assert texts(page.markup.inline_keyboard) == [["x"]]


async def test_a_bar_with_no_buttons_adds_no_row() -> None:
    class NextOnly(ArrowPagination[int]):
        def nav_row(
            self, number: int, total_pages: int | None, has_next: bool
        ) -> list[InlineKeyboardButton]:
            return [self.nav_button("More", number + 1, number, total_pages)] if has_next else []

    page = await NextOnly(
        [1, 2, 3], item=item_button, arrangement=PageArrangement(lines=2, columns=1)
    ).build(2)

    assert texts(page.markup.inline_keyboard) == [["i3"]]


async def test_unknown_count_past_the_end_keeps_the_way_back() -> None:
    page = await ArrowPagination(
        Fetch(0),
        item=item_button,
        arrangement=PageArrangement(lines=2, columns=1),
        first_if_empty=False,
    ).build(5)

    assert page.items == []
    assert page.has_next is False
    assert texts(page.markup.inline_keyboard) == [["‹"]]


# --- nav_button -------------------------------------------------------------


def test_nav_button_to_another_page() -> None:
    pages = make_pages(
        9, page_data=lambda page: f"p{page}", style=BarStyle(nav=paint(ButtonStyle.PRIMARY))
    )
    button = pages.nav_button("{page}/{pages}", 3, 2, 9)

    assert button.text == "3/9"
    assert button.callback_data == "p3"
    assert button.style is ButtonStyle.PRIMARY
    assert button.disabled is None


def test_nav_button_to_the_current_page_is_disabled_with_its_own_data() -> None:
    pages = make_pages(
        9, page_data=lambda page: f"p{page}", style=BarStyle(current=paint(ButtonStyle.SUCCESS))
    )
    button = pages.nav_button("{page}", 2, 2, 9)

    assert button.callback_data == "p2"
    assert button.style is ButtonStyle.SUCCESS
    assert isinstance(button.disabled, DisabledButton)


def test_nav_button_gives_each_built_button_to_its_own_function() -> None:
    nav, current = Mock(), Mock()
    pages = make_pages(9, style=BarStyle(nav=nav, current=current))

    other = pages.nav_button("{page}", 3, 2, 9)
    same = pages.nav_button("{page}", 2, 2, 9)

    assert nav.call_args_list == [((other,),)]
    assert current.call_args_list == [((same,),)]
    assert nav.call_args.args[0] is other
    assert current.call_args.args[0] is same


@pytest.mark.parametrize("target", [2, 3])
def test_nav_button_without_a_style_has_the_default_one(target: int) -> None:
    assert make_pages(9).nav_button("x", target, 2, 9).style is ButtonStyle.DEFAULT


def test_nav_button_does_not_raise_on_pages_with_an_unknown_count() -> None:
    assert make_arrows(9).nav_button("{page}/{pages}", 3, 2, None).text == "3/None"


# --- NumberedPagination -----------------------------------------------------


def test_numbered_refuses_a_fetch_without_a_count() -> None:
    with pytest.raises(TypeError, match="needs the count"):
        NumberedPagination(Fetch(1), item=item_button)


def test_numbered_defaults() -> None:
    pages = make_pages(1)

    bar_texts = pages.texts

    assert (
        bar_texts.first,
        bar_texts.previous,
        bar_texts.current,
        bar_texts.next,
        bar_texts.last,
    ) == (
        "« {page}",
        "‹ {page}",
        "· {page} ·",
        "{page} ›",
        "{page} »",
    )


@pytest.mark.parametrize("total", range(1, 13))
async def test_numbered_bar_on_every_page(total: int) -> None:
    pages = make_pages(
        total, arrangement=PageArrangement(lines=1, columns=1), page_data=lambda page: f"p{page}"
    )

    for number in range(1, total + 1):
        rows = await rows_of(pages, number)

        assert texts(rows[:1]) == [[f"i{number}"]]

        if total == 1:
            assert len(rows) == 1
            continue

        shown = {number - 1, number + 1, 1, number, total}
        numbers = [int(button.callback_data[1:]) for button in rows[-1]]
        disabled = [n for n, button in zip(numbers, rows[-1], strict=True) if button.disabled]

        assert numbers == sorted(shown & set(range(1, total + 1)))
        assert disabled == [number]


@pytest.mark.parametrize(
    ("number", "expected"),
    [
        (1, ["· 1 ·", "2 ›", "12 »"]),
        (2, ["« 1", "· 2 ·", "3 ›", "12 »"]),
        (6, ["« 1", "‹ 5", "· 6 ·", "7 ›", "12 »"]),
        (11, ["« 1", "‹ 10", "· 11 ·", "12 »"]),
        (12, ["« 1", "‹ 11", "· 12 ·"]),
    ],
)
async def test_numbered_bar_labels(number: int, expected: list[str]) -> None:
    assert (
        await bar(make_pages(12, arrangement=PageArrangement(lines=1, columns=1)), number)
        == expected
    )


def test_numbered_takes_its_texts_from_its_labels() -> None:
    pages = make_pages(
        9,
        texts=NumberedBarTexts(
            first="f{page}", previous="p{page}", current="c{page}", next="n{page}", last="l{pages}"
        ),
    )

    assert texts([pages.nav_row(5, 9, True)]) == [["f1", "p4", "c5", "n6", "l9"]]


# --- ArrowPagination --------------------------------------------------------


@pytest.mark.parametrize(
    ("counter", "number", "expected"),
    [
        (None, 1, ["›"]),
        (None, 2, ["‹", "›"]),
        (None, 3, ["‹"]),
        ("{page}/{pages}", 1, ["1/3", "›"]),
        ("{page}/{pages}", 2, ["‹", "2/3", "›"]),
        ("{page}/{pages}", 3, ["‹", "3/3"]),
    ],
)
async def test_arrow_bar_with_a_known_count(
    counter: str | None, number: int, expected: list[str]
) -> None:
    assert (
        await bar(
            make_arrows(
                3,
                arrangement=PageArrangement(lines=1, columns=1),
                texts=ArrowBarTexts(counter=counter),
            ),
            number,
        )
        == expected
    )


@pytest.mark.parametrize(
    ("counter", "number", "expected"),
    [
        (None, 1, ["›"]),
        (None, 2, ["‹", "›"]),
        (None, 3, ["‹"]),
        ("{page}/{pages}", 1, ["p1", "›"]),
        ("{page}/{pages}", 2, ["‹", "p2", "›"]),
        ("{page}/{pages}", 3, ["‹", "p3"]),
    ],
)
async def test_arrow_bar_with_an_unknown_count(
    counter: str | None, number: int, expected: list[str]
) -> None:
    pages = ArrowPagination(
        Fetch(3),
        item=item_button,
        arrangement=PageArrangement(lines=1, columns=1),
        texts=ArrowBarTexts(counter=counter, unknown_counter="p{page}"),
    )

    assert await bar(pages, number) == expected


async def test_arrow_bar_targets_and_disabled_counter() -> None:
    pages = make_arrows(
        3,
        arrangement=PageArrangement(lines=1, columns=1),
        texts=ArrowBarTexts(counter="{page}"),
        page_data=lambda page: f"p{page}",
    )
    row = (await rows_of(pages, 2))[-1]

    assert [button.callback_data for button in row] == ["p1", "p2", "p3"]
    assert [button.disabled is not None for button in row] == [False, True, False]


async def test_arrow_bar_has_no_disabled_button_without_a_counter() -> None:
    row = (await rows_of(make_arrows(3, arrangement=PageArrangement(lines=1, columns=1)), 2))[-1]

    assert not any(button.disabled for button in row)


def test_arrow_takes_its_texts_from_its_labels() -> None:
    row = make_arrows(
        9, texts=ArrowBarTexts(back="b{page}", forward="f{page}", counter="{page}of{pages}")
    ).nav_row(5, 9, True)

    assert texts([row]) == [["b4", "5of9", "f6"]]


# --- a pagination written by a user -----------------------------------------


class JumpTen(Pagination[int]):
    def nav_row(
        self, number: int, total_pages: int | None, has_next: bool
    ) -> list[InlineKeyboardButton]:
        return [self.nav_button("+10 of {pages}", number + 10, number, total_pages)]


async def test_a_subclass_supplies_its_own_bar() -> None:
    pages = JumpTen(
        list(range(1, 50)),
        item=item_button,
        arrangement=PageArrangement(lines=1, columns=1),
        page_data=lambda p: f"p{p}",
    )
    row = (await rows_of(pages, 3))[-1]

    assert [(button.text, button.callback_data) for button in row] == [("+10 of 49", "p13")]


async def test_a_subclass_gets_no_bar_on_a_single_page() -> None:
    assert texts(await rows_of(JumpTen([1], item=item_button))) == [["i1"]]


def make_sliding(count: int, **kw: Any) -> SlidingPagination[int]:
    return SlidingPagination(
        list(range(1, count + 1)),
        item=item_button,
        arrangement=PageArrangement(lines=1, columns=1),
        **kw,
    )


def numbers(first: int, last: int, current: int) -> list[str]:
    return [f"· {page} ·" if page == current else str(page) for page in range(first, last + 1)]


async def test_sliding_bar_shows_every_page_when_they_fit() -> None:
    assert await bar(make_sliding(8), 3) == numbers(1, 8, 3)


@pytest.mark.parametrize(
    ("number", "first", "last"),
    [
        (1, 1, 8),
        (7, 1, 8),
        (8, 7, 14),
        (13, 7, 14),
        (14, 13, 20),
        (20, 19, 26),
        (26, 25, 30),
        (29, 25, 30),
        (30, 25, 30),
    ],
)
async def test_sliding_bar_brings_the_next_pages_at_the_last_number(
    number: int, first: int, last: int
) -> None:
    assert await bar(make_sliding(30), number) == numbers(first, last, number)


async def test_sliding_bar_is_not_pulled_back_near_the_end() -> None:
    assert await bar(make_sliding(10), 8) == numbers(7, 10, 8)


@pytest.mark.parametrize("size", [3, 4, 5, 8])
@pytest.mark.parametrize("total", [1, 2, 5, 9, 40])
def test_sliding_bar_always_shows_both_neighbours(size: int, total: int) -> None:
    pages = make_sliding(total, bar=SlidingBar(size=size))

    for number in range(1, total + 1):
        row = pages.nav_row(number, total, number < total)
        shown = [int(button.callback_data) for button in row]

        assert len(shown) <= size
        assert {max(number - 1, 1), number, min(number + 1, total)} <= set(shown)


async def test_sliding_bar_uses_its_texts_and_buttons() -> None:
    pages = make_sliding(
        3,
        bar=SlidingBar(page="p{page}/{pages}", current="[{page}]"),
        page_data=lambda n: f"go:{n}",
        style=BarStyle(nav=paint(ButtonStyle.PRIMARY)),
    )

    row = (await rows_of(pages, 2))[-1]

    assert [button.text for button in row] == ["p1/3", "[2]", "p3/3"]
    assert [button.callback_data for button in row] == ["go:1", "go:2", "go:3"]
    assert row[0].style is ButtonStyle.PRIMARY
    assert row[1].style is ButtonStyle.DEFAULT
    assert isinstance(row[1].disabled, DisabledButton)


async def test_sliding_pagination_fetches_with_a_count() -> None:
    pages = SlidingPagination(
        Fetch(3),
        item=item_button,
        count=ItemCount(3, strict=False),
        arrangement=PageArrangement(lines=1, columns=1),
    )

    assert await bar(pages, 2) == numbers(1, 3, 2)


def test_sliding_pagination_refuses_a_fetch_without_a_count() -> None:
    with pytest.raises(TypeError, match="SlidingPagination needs the count"):
        SlidingPagination(Fetch(3), item=item_button)


async def test_a_count_function_returning_a_negative_number_counts_no_items() -> None:
    page = await NumberedPagination(
        list(range(1, 11)),
        item=item_button,
        count=ItemCount(lambda: -1),
        arrangement=PageArrangement(lines=5, columns=1),
    ).build()

    assert (list(page.items), page.total_pages) == ([], 0)


async def test_an_empty_page_stays_without_first_if_empty() -> None:
    page = await NumberedPagination(
        Fetch(2),
        item=item_button,
        count=ItemCount(6, strict=False),
        arrangement=PageArrangement(lines=2, columns=1),
        first_if_empty=False,
    ).build(3)

    assert (page.number, list(page.items), page.total_pages) == (3, [], 3)


async def test_first_if_empty_replaces_a_page_past_an_unknown_end() -> None:
    fetch = Fetch(3)
    page = await ArrowPagination(
        fetch,
        item=item_button,
        arrangement=PageArrangement(lines=2, columns=1),
        first_if_empty=True,
    ).build(5)

    assert (page.number, list(page.items)) == (1, [1, 2])
    assert fetch.calls == [(8, 3), (0, 3)]


async def test_first_if_empty_replaces_a_page_of_a_stale_count() -> None:
    fetch = Fetch(2)
    page = await NumberedPagination(
        fetch,
        item=item_button,
        count=ItemCount(6, strict=False),
        arrangement=PageArrangement(lines=2, columns=1),
        first_if_empty=True,
    ).build(3)

    assert (page.number, list(page.items)) == (1, [1, 2])
    assert fetch.calls == [(4, 2), (0, 2)]


async def test_first_if_empty_reads_the_count_again() -> None:
    counts = iter([6, 2])
    page = await NumberedPagination(
        Fetch(2),
        item=item_button,
        count=ItemCount(lambda: next(counts), strict=False),
        arrangement=PageArrangement(lines=2, columns=1),
        first_if_empty=True,
    ).build(3)

    assert (page.number, page.total_pages) == (1, 1)


async def test_first_if_empty_does_not_loop_on_an_empty_first_page() -> None:
    fetch = Fetch(0)
    page = await NumberedPagination(
        fetch,
        item=item_button,
        count=ItemCount(4, strict=False),
        arrangement=PageArrangement(lines=2, columns=1),
        first_if_empty=True,
    ).build()

    assert (page.number, list(page.items)) == (1, [])
    assert fetch.calls == [(0, 2)]


async def test_sliding_bar_shows_every_page_on_the_last_one_when_they_fit() -> None:
    assert await bar(make_sliding(8), 8) == numbers(1, 8, 8)


async def test_sliding_bar_keeps_the_last_page_in_the_group_before_it() -> None:
    assert await bar(make_sliding(14), 14) == numbers(7, 14, 14)


@pytest.mark.parametrize("make", [make_pages, make_arrows, make_sliding])
def test_paginations_have_no_instance_dict(make: Any) -> None:
    assert not hasattr(make(1), "__dict__")


async def test_a_strict_count_fetches_and_shows_only_what_is_left() -> None:
    fetch = Fetch(10)
    page = await NumberedPagination(
        fetch, item=item_button, count=ItemCount(3), arrangement=PageArrangement(lines=2, columns=1)
    ).build(2)

    assert (list(page.items), page.total_pages, page.has_next) == ([3], 2, False)
    assert fetch.calls == [(2, 1)]


async def test_a_lenient_count_fetches_a_whole_last_page() -> None:
    fetch = Fetch(10)
    page = await NumberedPagination(
        fetch,
        item=item_button,
        count=ItemCount(3, strict=False),
        arrangement=PageArrangement(lines=2, columns=1),
    ).build(2)

    assert (list(page.items), page.total_pages, page.has_next) == ([3, 4], 2, False)
    assert fetch.calls == [(2, 2)]


async def test_a_strict_count_holds_when_fetch_returns_more() -> None:
    page = await NumberedPagination(
        Fetch(10, extra=5),
        item=item_button,
        count=ItemCount(3),
        arrangement=PageArrangement(lines=2, columns=1),
    ).build(2)

    assert list(page.items) == [3]


async def test_a_strict_count_of_zero_never_fetches() -> None:
    fetch = Fetch(5)
    page = await NumberedPagination(
        fetch, item=item_button, count=ItemCount(0), arrangement=PageArrangement(lines=2, columns=1)
    ).build()

    assert (list(page.items), page.total_pages) == ([], 0)
    assert fetch.calls == []


async def test_a_count_function_is_read_on_every_build() -> None:
    answers = iter([3, 5])
    pages = NumberedPagination(
        Fetch(10),
        item=item_button,
        count=ItemCount(lambda: next(answers)),
        arrangement=PageArrangement(lines=2, columns=1),
    )

    assert list((await pages.build(2)).items) == [3]
    assert list((await pages.build(2)).items) == [3, 4]


@pytest.mark.parametrize("count", [0, 1, 9])
async def test_build_puts_the_header_first_on_every_kind_of_page(count: int) -> None:
    pages = make_pages(count, header=[[btn("h", "h")]], footer=[[btn("f", "f")]])
    rows = await rows_of(pages)

    assert (rows[0][0].text, rows[-1][0].text) == ("h", "f")


async def test_build_orders_the_header_items_bar_and_footer() -> None:
    pages = make_pages(
        2,
        arrangement=PageArrangement(lines=1, columns=1),
        header=[[btn("h", "h")]],
        footer=[[btn("f", "f")]],
    )

    assert texts(await rows_of(pages)) == [["h"], ["i1"], ["· 1 ·", "2 »"], ["f"]]
