"""Tests for `pyroflow.keyboards.layout`: `arrange`, and the package surface."""

from __future__ import annotations as _annotations

import pytest

import pyroflow
from pyroflow import keyboards
from pyroflow.keyboards import arrange
from pyroflow.keyboards import layout as module


def items(count: int) -> list[str]:
    return [str(n) for n in range(1, count + 1)]


def test_module_all() -> None:
    assert module.__all__ == ("arrange",)


def test_package_exposes_the_names() -> None:
    assert "arrange" in pyroflow.__all__
    assert pyroflow.arrange is arrange


@pytest.mark.parametrize("name", ["btn", "ikb", "rkb", "Choices", "confirm"])
def test_removed_names_are_gone(name: str) -> None:
    assert not hasattr(keyboards, name)


def test_arrange_puts_one_button_per_row_by_default() -> None:
    assert arrange(items(2)) == [["1"], ["2"]]


def test_arrange_of_nothing_is_empty() -> None:
    assert arrange([], columns=2) == []


def test_arrange_with_a_fixed_width() -> None:
    assert arrange(items(5), columns=2) == [["1", "2"], ["3", "4"], ["5"]]


def test_arrange_goes_on_with_the_last_size_of_a_layout() -> None:
    assert arrange(items(5), layout=[1, 2]) == [["1"], ["2", "3"], ["4", "5"]]


def test_arrange_repeats_a_layout() -> None:
    assert arrange(items(7), layout=[1, 2], repeat=True) == [
        ["1"],
        ["2", "3"],
        ["4"],
        ["5", "6"],
        ["7"],
    ]


def test_arrange_refuses_columns_with_layout() -> None:
    with pytest.raises(ValueError, match="not both"):
        arrange(items(1), columns=2, layout=[1])


@pytest.mark.parametrize(("columns", "layout"), [(0, None), (-1, None), (None, []), (None, [1, 0])])
def test_arrange_refuses_a_width_that_is_not_positive_even_without_buttons(
    columns: int | None, layout: list[int] | None
) -> None:
    with pytest.raises(ValueError, match="must be positive"):
        arrange([], columns=columns, layout=layout)
