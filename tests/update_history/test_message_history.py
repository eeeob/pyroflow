"""Tests for ``MessageHistory``."""

from __future__ import annotations as _annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING

import pytest

from pyroflow import MessageHistory

if TYPE_CHECKING:
    from pyrogram.types import Message

from ..conftest import make_callback_query, make_message


async def test_message_history_works_out_of_the_box() -> None:
    """A bare MessageHistory() ships working extractors, so it records without NotImplementedError."""
    history = MessageHistory()
    msg = make_message(100, 7, 5, text="hello")
    assert await history.extract_key(msg) == ("", 0, 100, 5, 7)
    assert await history.extract_data(msg) == "hello"


def test_init_keeps_each_given_callable() -> None:
    def key(u: Message) -> tuple[str]:
        return ("custom",)

    history = MessageHistory(extract_key_func=key)
    assert history.extract_key_func is key
    # the other one still falls back to the built-in
    assert history.extract_data_func == history._extract_data


async def test_init_custom_callable_is_used_over_the_built_in() -> None:
    history = MessageHistory(extract_data_func=lambda u: u.id)
    assert await history.extract_data(make_message(message_id=9, text="hi")) == 9


async def test_extract_key_is_none_without_chat() -> None:
    assert await MessageHistory()._extract_key(make_message(chat=None)) is None


async def test_extract_key_user_id_is_none_without_sender() -> None:
    msg = make_message(100, 7, 5, from_user=None)
    assert await MessageHistory()._extract_key(msg) == ("", 0, 100, 5, None)


async def test_extract_key_keeps_business_scheduled_and_ephemeral_messages_apart() -> None:
    history = MessageHistory()
    business = make_message(100, 7, 5)
    business.business_connection_id = "conn-1"
    scheduled = make_message(100, 7, 5)
    scheduled.scheduled = True
    ephemerals = []
    for day in (1, 2):
        ephemeral = make_message(100, 7, 0)
        ephemeral.ephemeral_message_id = 1
        ephemeral.date = datetime(2026, 1, day, tzinfo=timezone.utc)
        ephemerals.append(ephemeral)

    messages = (make_message(100, 7, 5), business, scheduled, *ephemerals)
    keys = {await history._extract_key(m) for m in messages}

    assert len(keys) == len(messages)


async def test_extract_key_ignores_edits() -> None:
    history = MessageHistory()
    edited = make_message(100, 7, 5)
    edited.edit_date = datetime(2026, 1, 1, tzinfo=timezone.utc)

    assert await history._extract_key(edited) == await history._extract_key(make_message(100, 7, 5))


async def test_extract_data_is_message_text() -> None:
    assert await MessageHistory()._extract_data(make_message(text="hello")) == "hello"


async def test_message_history_rejects_callback_query() -> None:
    with pytest.raises(TypeError, match="Expected Message, got CallbackQuery"):
        await MessageHistory().extract_key(make_callback_query())
