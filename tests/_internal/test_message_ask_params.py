"""Tests for `pyroflow._internal.message_ask_params`."""

from __future__ import annotations as _annotations

import inspect
from typing import TYPE_CHECKING

import pyroflow
from pyroflow._internal import message_ask_params as module
from pyroflow._internal.message_ask_params import (
    MessageAskEditKw,
    MessageAskRichEditKw,
    MessageAskRichSendKw,
    MessageAskSendKw,
)

if TYPE_CHECKING:
    from collections.abc import Callable


def _params(func: Callable[..., object], *owned: str) -> set[str]:
    return set(inspect.signature(func).parameters) - {"self", "chat_id", *owned}


def test_module_all() -> None:
    assert module.__all__ == (
        "MessageAskSendKw",
        "MessageAskEditKw",
        "MessageAskRichSendKw",
        "MessageAskRichEditKw",
    )


def test_message_ask_send_kw_covers_send_message() -> None:
    params = _params(pyroflow.Client.send_message, "text", "business_connection_id")
    assert params <= MessageAskSendKw.__optional_keys__


def test_message_ask_edit_kw_covers_edit_message_text() -> None:
    params = _params(
        pyroflow.Client.edit_message_text,
        "message_id",
        "text",
        "rich_message",
        "business_connection_id",
    )
    assert params <= MessageAskEditKw.__optional_keys__


def test_message_ask_rich_send_kw_covers_send_rich_message() -> None:
    params = _params(pyroflow.Client.send_rich_message, "rich_message", "business_connection_id")
    assert params <= MessageAskRichSendKw.__optional_keys__


def test_message_ask_rich_edit_kw_leaves_out_what_only_text_takes() -> None:
    keys = MessageAskRichEditKw.__optional_keys__
    assert keys == {"schedule_date", "reply_markup"}


def test_message_kw_leave_out_what_the_message_supplies() -> None:
    for kw in (MessageAskSendKw, MessageAskEditKw, MessageAskRichSendKw, MessageAskRichEditKw):
        assert "business_connection_id" not in kw.__optional_keys__
