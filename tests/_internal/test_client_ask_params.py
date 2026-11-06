"""Tests for `pyroflow._internal.client_ask_params`."""

from __future__ import annotations as _annotations

import pytest

import pyroflow
from pyroflow._internal import client_ask_params as module
from pyroflow._internal.client_ask_params import (
    AskEditKw,
    AskRichEditKw,
    AskRichSendKw,
    AskSendKw,
)
from pyroflow._internal.message_ask_params import (
    MessageAskEditKw,
    MessageAskRichEditKw,
    MessageAskRichSendKw,
    MessageAskSendKw,
)


def test_module_all() -> None:
    assert module.__all__ == ("AskSendKw", "AskEditKw", "AskRichSendKw", "AskRichEditKw")


@pytest.mark.parametrize(
    ("client_kw", "message_kw"),
    [
        (AskSendKw, MessageAskSendKw),
        (AskEditKw, MessageAskEditKw),
        (AskRichSendKw, MessageAskRichSendKw),
        (AskRichEditKw, MessageAskRichEditKw),
    ],
)
def test_client_kw_add_the_business_connection_to_the_message_ones(
    client_kw: type, message_kw: type
) -> None:
    extra = client_kw.__optional_keys__ - message_kw.__optional_keys__
    assert extra == {"business_connection_id"}


def test_package_stays_out_of_the_public_names() -> None:
    assert not hasattr(pyroflow, "AskSendKw")
    assert "AskSendKw" not in pyroflow.__all__
