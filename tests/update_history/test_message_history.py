"""Tests for ``MessageHistory``."""

from __future__ import annotations as _annotations

from typing import TYPE_CHECKING

import pytest

from pyroflow import MessageHistory

if TYPE_CHECKING:
    from pyrogram.types import Message

from ..conftest import make_callback_query, make_message


async def test_message_history_works_out_of_the_box() -> None:
    """A bare MessageHistory() ships working extractors, matching
    CallbackQueryHistory, so it records without raising NotImplementedError."""
    history = MessageHistory()
    msg = make_message(100, 7, 5, text="hello")
    assert await history.is_recordable(msg) is True
    assert await history.extract_key(msg) == (100, 7, 5)
    assert await history.extract_data(msg) == "hello"


async def test_message_history_records_end_to_end() -> None:
    history = MessageHistory()
    await history.start()
    try:
        msg = make_message(100, 7, 5, text="hi")
        await history.record(msg, handler="H")
        recs = await history.get(msg)
        assert [r.handler for r in recs] == ["H"]
        assert recs[0].data == "hi"
    finally:
        await history.stop()


def test_init_keeps_each_given_callable() -> None:
    def key(u: Message) -> str:
        return "custom"

    history = MessageHistory(extract_key_func=key)
    assert history.extract_key_func is key
    # the other two still fall back to the built-ins
    assert history.is_recordable_func == history._is_recordable
    assert history.extract_data_func == history._extract_data


async def test_init_custom_callable_is_used_over_the_built_in() -> None:
    history = MessageHistory(is_recordable_func=lambda u: False, extract_data_func=lambda u: u.id)
    msg = make_message(message_id=9, text="hi")
    assert await history.is_recordable(msg) is False
    assert await history.extract_data(msg) == 9


async def test_is_recordable_false_without_chat() -> None:
    history = MessageHistory()
    msg = make_message(chat=None)
    assert await history._is_recordable(msg) is False
    await history.record(msg, "H")
    assert await history.get(msg) == []


async def test_extract_key_user_id_is_none_without_sender() -> None:
    msg = make_message(100, 7, 5, from_user=None)
    assert await MessageHistory()._extract_key(msg) == (100, None, 5)


async def test_extract_data_is_message_text() -> None:
    assert await MessageHistory()._extract_data(make_message(text="hello")) == "hello"


async def test_message_history_rejects_callback_query() -> None:
    with pytest.raises(TypeError, match="Expected Message, got CallbackQuery"):
        await MessageHistory().is_recordable(make_callback_query())
