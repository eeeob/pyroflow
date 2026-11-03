"""Tests for ``CallbackQueryHistory``."""

from __future__ import annotations as _annotations

from typing import TYPE_CHECKING

import pytest

from pyroflow import CallbackQueryHistory

if TYPE_CHECKING:
    from pyrogram.types import CallbackQuery

from ..conftest import make_callback_query, make_message


async def test_callback_query_history_works_out_of_the_box() -> None:
    history = CallbackQueryHistory()
    cbq = make_callback_query(100, 7, 5, data="payload")
    assert await history.extract_key(cbq) == (100, 7, 5)
    assert await history.extract_data(cbq) == "payload"


def test_init_keeps_each_given_callable() -> None:
    def data(u: CallbackQuery) -> str:
        return "custom"

    history = CallbackQueryHistory(extract_data_func=data)
    assert history.extract_data_func is data
    # the other one still falls back to the built-in
    assert history.extract_key_func == history._extract_key


async def test_init_custom_callable_is_used_over_the_built_in() -> None:
    history = CallbackQueryHistory(extract_key_func=lambda u: (u.id,))
    assert await history.extract_key(make_callback_query()) == ("cbq-1",)


async def test_extract_key_is_none_without_message() -> None:
    assert await CallbackQueryHistory()._extract_key(make_callback_query(message=None)) is None


async def test_extract_key_is_none_when_message_has_no_chat() -> None:
    cbq = make_callback_query(message=make_message(chat=None))
    assert await CallbackQueryHistory()._extract_key(cbq) is None


async def test_extract_key_uses_query_sender_not_message_sender() -> None:
    cbq = make_callback_query(100, 7, 5, message=make_message(200, 99, 8))
    assert await CallbackQueryHistory()._extract_key(cbq) == (200, 7, 8)


async def test_extract_key_user_id_is_none_without_sender() -> None:
    cbq = make_callback_query(100, 7, 5, from_user=None)
    assert await CallbackQueryHistory()._extract_key(cbq) == (100, None, 5)


@pytest.mark.parametrize("data", ["payload", b"\x00raw", None])
async def test_extract_data_is_callback_data(data: str | bytes | None) -> None:
    cbq = make_callback_query()
    cbq.data = data
    assert await CallbackQueryHistory()._extract_data(cbq) == data


async def test_callback_query_history_rejects_message() -> None:
    with pytest.raises(TypeError, match="Expected CallbackQuery, got Message"):
        await CallbackQueryHistory().extract_key(make_message())
