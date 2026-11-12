"""Tests for `pyroflow._internal.client_ask_params`."""

from __future__ import annotations as _annotations

import inspect
from typing import Any, TYPE_CHECKING

import pytest

import pyroflow
from pyroflow._internal import client_ask_params as module
from pyroflow._internal.client_ask_params import (
    AskEditKw,
    AskRichEditKw,
    AskRichSendKw,
    AskSendKw,
)

if TYPE_CHECKING:
    from collections.abc import Callable


_NOT_FOR_ASK = ("schedule_date", "repeat_period")
"""What Pyrogram accepts and `ask` leaves out: it waits for the answer to a question asked now."""


def _params(func: Callable[..., object], *owned: str) -> set[str]:
    return set(inspect.signature(func).parameters) - {"self", "chat_id", *owned}


def test_module_all() -> None:
    assert module.__all__ == (
        "AskSendKw",
        "AskEditKw",
        "AskRichSendKw",
        "AskRichEditKw",
    )


def test_ask_send_kw_covers_send_message() -> None:
    params = _params(pyroflow.Client.send_message, "text", *_NOT_FOR_ASK)
    assert params <= AskSendKw.__optional_keys__


def test_ask_edit_kw_covers_edit_message_text() -> None:
    # Pyrogram returns no message for a business edit, so `ask` cannot wait on one.
    params = _params(
        pyroflow.Client.edit_message_text,
        "message_id",
        "text",
        "rich_message",
        "business_connection_id",
        *_NOT_FOR_ASK,
    )
    assert params <= AskEditKw.__optional_keys__


def test_ask_edit_kw_fits_the_send_of_a_retry() -> None:
    # `Client.ask_until` sends its retries with the arguments the first question edited with.
    assert AskEditKw.__optional_keys__ <= AskSendKw.__optional_keys__


@pytest.mark.parametrize("kw", [AskSendKw, AskEditKw, AskRichSendKw, AskRichEditKw])
def test_nothing_that_puts_the_question_off_is_accepted(kw: Any) -> None:
    assert not kw.__optional_keys__ & set(_NOT_FOR_ASK)


def test_ask_edit_kws_leave_out_the_business_connection() -> None:
    assert "business_connection_id" not in AskEditKw.__optional_keys__
    assert "business_connection_id" not in AskRichEditKw.__optional_keys__


def test_ask_rich_send_kw_covers_send_rich_message() -> None:
    params = _params(pyroflow.Client.send_rich_message, "rich_message")
    assert params <= AskRichSendKw.__optional_keys__


def test_ask_rich_edit_kw_leaves_out_what_only_text_takes() -> None:
    # `edit_message_text` reads `parse_mode` and `entities` only for a text.
    params = _params(
        pyroflow.Client.edit_message_text,
        "message_id",
        "text",
        "rich_message",
        "business_connection_id",
        "parse_mode",
        "entities",
        *_NOT_FOR_ASK,
    )
    assert params <= AskRichEditKw.__optional_keys__
    assert not {"parse_mode", "entities"} & AskRichEditKw.__optional_keys__


def test_package_stays_out_of_the_public_names() -> None:
    assert not hasattr(pyroflow, "AskSendKw")
    assert "AskSendKw" not in pyroflow.__all__
