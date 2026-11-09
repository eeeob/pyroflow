"""Tests for `pyroflow.models.page`: Page."""

from __future__ import annotations as _annotations

import dataclasses

import pytest
from pyrogram.types import InlineKeyboardMarkup

from pyroflow.models import Page
from pyroflow.models import page as page_module


def make_page(total_pages: int | None = 3) -> Page[str]:
    return Page(2, ["a"], total_pages, True, InlineKeyboardMarkup([]))


def test_module_all() -> None:
    assert page_module.__all__ == ("Page",)


def test_page_keeps_its_fields() -> None:
    page = make_page()

    assert (page.number, page.items, page.total_pages, page.has_next) == (2, ["a"], 3, True)
    assert isinstance(page.markup, InlineKeyboardMarkup)


def test_page_with_an_unknown_count() -> None:
    assert make_page(None).total_pages is None


def test_page_is_frozen() -> None:
    with pytest.raises(dataclasses.FrozenInstanceError):
        make_page().number = 1


def test_page_is_generic_in_its_item_type() -> None:
    assert Page.__parameters__ == (page_module._T,)
