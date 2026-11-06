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


def test_message_ask_send_kw_covers_reply() -> None:
    params = _params(pyroflow.types.Message.reply, "text")
    assert params == MessageAskSendKw.__optional_keys__


def test_message_ask_edit_kw_covers_edit() -> None:
    params = _params(pyroflow.types.Message.edit, "text", "rich_message")
    assert params == MessageAskEditKw.__optional_keys__


def test_message_ask_rich_send_kw_covers_reply_rich() -> None:
    params = _params(pyroflow.types.Message.reply_rich, "rich_message")
    assert params == MessageAskRichSendKw.__optional_keys__


def test_message_ask_rich_edit_kw_leaves_out_what_only_text_takes() -> None:
    assert MessageAskRichEditKw.__optional_keys__ == {"reply_markup"}
