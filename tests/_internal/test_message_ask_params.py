"""Tests for `pyroflow._internal.message_ask_params`."""

from __future__ import annotations as _annotations

import inspect
from typing import Any, TYPE_CHECKING

import pytest

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


_NOT_FOR_ASK = ("schedule_date", "repeat_period")
"""What Pyrogram accepts and `ask` leaves out: it waits for the answer to a question asked now."""


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
    params = _params(pyroflow.types.Message.reply, "text", *_NOT_FOR_ASK)
    assert params == MessageAskSendKw.__optional_keys__


def test_message_ask_edit_kw_covers_edit() -> None:
    params = _params(pyroflow.types.Message.edit, "text", "rich_message")
    assert params == MessageAskEditKw.__optional_keys__


def test_message_ask_edit_kw_fits_the_reply_of_a_retry() -> None:
    # `Message.ask_until` replies on retries with the arguments the first question edited with.
    assert MessageAskEditKw.__optional_keys__ <= MessageAskSendKw.__optional_keys__


@pytest.mark.parametrize(
    "kw",
    [
        MessageAskSendKw,
        MessageAskEditKw,
        MessageAskRichSendKw,
        MessageAskRichEditKw,
    ],
)
def test_nothing_that_puts_the_question_off_is_accepted(kw: Any) -> None:
    assert not kw.__optional_keys__ & set(_NOT_FOR_ASK)


def test_message_ask_rich_send_kw_covers_reply_rich() -> None:
    params = _params(pyroflow.types.Message.reply_rich, "rich_message")
    assert params == MessageAskRichSendKw.__optional_keys__


def test_message_ask_rich_edit_kw_leaves_out_what_only_text_takes() -> None:
    # `Message.edit` reads `parse_mode` and `entities` only for a text.
    params = _params(pyroflow.types.Message.edit, "text", "rich_message", "parse_mode", "entities")
    assert params == MessageAskRichEditKw.__optional_keys__
