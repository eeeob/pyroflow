"""Tests for `pyroflow.types.callback_query`: the patched `CallbackQuery`."""

from __future__ import annotations as _annotations

import pyrogram

from pyroflow.types import CallbackQuery
from pyroflow.types import callback_query as callback_query_module


def test_callback_query_all() -> None:
    assert callback_query_module.__all__ == ("CallbackQuery",)


def test_callback_query_patches_pyrogram_in_place() -> None:
    assert CallbackQuery is pyrogram.types.CallbackQuery
