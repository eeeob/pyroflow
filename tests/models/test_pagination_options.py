"""Tests for `pyroflow.models.pagination_options`: the options of a `Pagination`."""

from __future__ import annotations as _annotations

import dataclasses
from itertools import combinations
from typing import Any

import pytest

from pyroflow.models import (
    ArrowBarTexts,
    BarStyle,
    ItemCount,
    NumberedBarTexts,
    PageArrangement,
    SlidingBar,
)
from pyroflow.models import pagination_options as module

OPTIONS = [
    PageArrangement(lines=1, columns=1),
    BarStyle(),
    NumberedBarTexts(),
    ArrowBarTexts(),
    SlidingBar(),
    ItemCount(1),
]


def test_module_all() -> None:
    assert module.__all__ == (
        "PageArrangement",
        "ItemCount",
        "BarStyle",
        "NumberedBarTexts",
        "ArrowBarTexts",
        "SlidingBar",
    )


def test_sliding_bar_defaults() -> None:
    assert dataclasses.astuple(SlidingBar()) == (8, "{page}", "· {page} ·")


@pytest.mark.parametrize("size", [2, 0, -1])
def test_sliding_bar_refuses_a_size_under_three(size: int) -> None:
    with pytest.raises(ValueError, match="at least 3"):
        SlidingBar(size=size)


@pytest.mark.parametrize(
    ("kw", "expected"),
    [
        ({"lines": 2, "columns": 3}, 6),
        ({"layout": [1, 2]}, 3),
        ({"layout": [1, 2], "repeat": True, "per_page": 5}, 5),
        ({"layout": [1, 2], "per_page": 5}, 5),
        ({"layout": [1, 2], "per_page": 3}, 3),
        ({"layout": [1, 2], "repeat": True, "per_page": 2}, 2),
        ({"lines": 3, "layout": [1, 2], "repeat": True}, 4),
        ({"columns": 2, "per_page": 5}, 5),
    ],
)
def test_page_arrangement_works_out_per_page(kw: dict[str, Any], expected: int) -> None:
    assert PageArrangement(**kw).per_page == expected


@pytest.mark.parametrize(
    ("kw", "message"),
    [
        ({"columns": 1, "layout": [1]}, "columns or layout"),
        ({"columns": 2, "layout": [1], "repeat": True}, "columns or layout"),
        ({"lines": 2, "per_page": 4}, "lines or per_page"),
        ({"lines": 2, "columns": 3, "per_page": 6}, "lines or per_page"),
        ({"lines": 2, "layout": [1]}, "lines needs repeat"),
        ({"repeat": True}, "repeat needs layout"),
        ({"lines": 2, "repeat": True}, "repeat needs layout"),
        ({"columns": 2, "repeat": True}, "repeat needs layout"),
        ({"layout": [1, 2], "per_page": 2}, "cannot be less than the sum"),
        ({}, "Pass columns or layout"),
        ({"lines": 2}, "Pass columns or layout"),
        ({"per_page": 2}, "Pass columns or layout"),
        ({"columns": 2}, "Pass lines or per_page with"),
        ({"layout": [1], "repeat": True}, "Pass lines or per_page with"),
    ],
)
def test_page_arrangement_refuses_what_contradicts(kw: dict[str, Any], message: str) -> None:
    with pytest.raises(ValueError, match=message):
        PageArrangement(**kw)


def test_page_arrangement_accepts_only_the_documented_sets() -> None:
    values = {"lines": 2, "columns": 2, "layout": [1, 2], "repeat": True, "per_page": 4}
    documented = {
        frozenset(names)
        for names in (
            ("lines", "columns"),
            ("per_page", "columns"),
            ("layout",),
            ("layout", "per_page"),
            ("layout", "repeat", "lines"),
            ("layout", "repeat", "per_page"),
        )
    }

    for size in range(len(values) + 1):
        for names in combinations(values, size):
            kw = {name: values[name] for name in names}

            if frozenset(names) in documented:
                PageArrangement(**kw)
            else:
                with pytest.raises(ValueError, match="Pass|needs"):
                    PageArrangement(**kw)


@pytest.mark.parametrize(
    "kw",
    [
        {"lines": 0},
        {"lines": 0, "layout": [1]},
        {"per_page": 0},
        {"columns": 0},
        {"columns": 0, "per_page": 3},
        {"layout": []},
        {"layout": [1, 0]},
        {"layout": [0], "per_page": 3},
    ],
)
def test_page_arrangement_refuses_what_is_not_positive(kw: dict[str, Any]) -> None:
    with pytest.raises(ValueError, match="must be positive"):
        PageArrangement(**kw)


def test_bar_style_holds_no_functions_by_default() -> None:
    assert (BarStyle().nav, BarStyle().current) == (None, None)


def test_bar_style_keeps_its_functions_in_order() -> None:
    style = BarStyle(print, len)

    assert (style.nav, style.current) == (print, len)


def test_numbered_bar_texts_defaults() -> None:
    assert dataclasses.astuple(NumberedBarTexts()) == (
        "« {page}",
        "‹ {page}",
        "· {page} ·",
        "{page} ›",
        "{page} »",
    )


def test_arrow_bar_texts_defaults() -> None:
    assert dataclasses.astuple(ArrowBarTexts()) == ("‹", "›", None, "{page}")


@pytest.mark.parametrize("option", OPTIONS)
def test_options_are_frozen_and_slotted(option: Any) -> None:
    value = option
    name = dataclasses.fields(option)[0].name

    assert not hasattr(value, "__dict__")
    with pytest.raises(dataclasses.FrozenInstanceError):
        setattr(value, name, None)


def test_item_count_is_strict_by_default() -> None:
    assert ItemCount(3).strict is True


@pytest.mark.parametrize("value", [0, 3, len])
def test_item_count_accepts_a_number_or_a_function(value: Any) -> None:
    assert ItemCount(value).value is value


def test_item_count_refuses_a_negative_number() -> None:
    with pytest.raises(ValueError, match="must not be negative"):
        ItemCount(-1)
