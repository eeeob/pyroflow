"""Keyboard models: one built page of a `pyroflow.keyboards.Pagination`."""

from __future__ import annotations as _annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Generic, TypeVar

from pyrogram.types import InlineKeyboardMarkup


_T = TypeVar("_T")
"""The class of the items on a `Page`."""


@dataclass(frozen=True, slots=True)
class Page(Generic[_T]):
    """One page of a `Pagination`, as `build` returns it.

    Example:
        >>> page = Page(1, ["a"], None, False, InlineKeyboardMarkup([]))
        >>> page.number, page.items, page.total_pages, page.has_next
        (1, ['a'], None, False)
    """

    number: int
    """The page, from 1."""
    items: Sequence[_T]
    """The items on the page."""
    total_pages: int | None
    """How many pages there are; `None` when the count is unknown."""
    has_next: bool
    """Whether a page comes after this one."""
    markup: InlineKeyboardMarkup
    """The keyboard of the page."""


__all__ = ("Page",)
