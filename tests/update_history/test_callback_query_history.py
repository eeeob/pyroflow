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
    assert await history.is_recordable(cbq) is True
    assert await history.extract_key(cbq) == (100, 7, 5)
    assert await history.extract_data(cbq) == "payload"


def test_init_keeps_each_given_callable() -> None:
    def rec(u: CallbackQuery) -> bool:
        return False

    history = CallbackQueryHistory(is_recordable_func=rec)
    assert history.is_recordable_func is rec
    # the other two still fall back to the built-ins
    assert history.extract_key_func == history._extract_key
    assert history.extract_data_func == history._extract_data


async def test_init_custom_callable_is_used_over_the_built_in() -> None:
    history = CallbackQueryHistory(extract_key_func=lambda u: u.id)
    assert await history.extract_key(make_callback_query()) == "cbq-1"


async def test_records_end_to_end() -> None:
    history = CallbackQueryHistory()
    await history.start()
    try:
        cbq = make_callback_query(100, 7, 5, data="yes")
        await history.record(cbq, "menu")
        recs = await history.get((100, 7, 5))
        assert [(r.handler, r.data) for r in recs] == [("menu", "yes")]
    finally:
        await history.stop()


async def test_is_recordable_false_without_message() -> None:
    history = CallbackQueryHistory()
    cbq = make_callback_query(message=None)
    assert await history._is_recordable(cbq) is False
    await history.record(cbq, "H")
    assert await history.get(cbq) == []


async def test_is_recordable_false_when_message_has_no_chat() -> None:
    cbq = make_callback_query(message=make_message(chat=None))
    assert await CallbackQueryHistory()._is_recordable(cbq) is False


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
        await CallbackQueryHistory().is_recordable(make_message())
