"""Tests for ``MessageListener``: listenability and key extraction."""

from __future__ import annotations as _annotations

import logging
from datetime import datetime
from typing import Any, TYPE_CHECKING

import pytest
from pyrogram import filters

import pyroflow.update_listener.message_listener as message_listener_module
from pyroflow import MessageListener
from pyroflow.models import ListenerKey

from ..conftest import make_message

if TYPE_CHECKING:
    from pyrogram.filters import Filter

    from pyroflow.types import Message


# --- class / __init__ --------------------------------------------------------


def test_module_logger() -> None:
    assert message_listener_module.log.name == "pyroflow.update_listener.message_listener"


def test_init_defaults_to_builtin_key_and_listen_functions() -> None:
    lis = MessageListener()
    assert lis.extract_key_func == lis._extract_key
    assert lis.on_listen_func == lis._warn_single_update_filter


def test_init_keeps_given_functions_and_forwards_kwargs() -> None:
    def extract_key(update: Message) -> ListenerKey:
        return ListenerKey(1)

    lis = MessageListener(extract_key_func=extract_key, timeout=3)
    assert lis.extract_key_func is extract_key
    assert lis.timeout == 3


# --- _warn_single_update_filter ------------------------------------------------------


@pytest.mark.parametrize(
    ("message_id", "filters_", "strict", "warned"),
    [
        (5, filters.text, False, True),
        (5, filters.text, True, False),
        (5, None, False, False),
        (None, filters.text, False, False),
    ],
)
def test_warn_single_update_filter_warns_of_a_wait_a_rejected_message_leaves_open(
    caplog: pytest.LogCaptureFixture,
    message_id: int | None,
    filters_: Filter | None,
    strict: bool,
    warned: bool,
) -> None:
    with caplog.at_level(logging.WARNING, logger=message_listener_module.log.name):
        MessageListener()._warn_single_update_filter(
            {
                "chat_id": 1,
                "user_id": 2,
                "message_id": message_id,
                "context": None,
                "filters": filters_,
                "strict": strict,
                "timeout": None,
            }
        )

    assert ("waits for a single update with a non-strict filter" in caplog.text) is warned


# --- _extract_key -----------------------------------------------------------------


async def test_extract_key_uses_chat_sender_and_id() -> None:
    msg = make_message(chat_id=-100, user_id=9, message_id=42)
    assert await MessageListener()._extract_key(msg) == ListenerKey(-100, 9, 42)


async def test_extract_key_without_sender_has_no_user() -> None:
    msg = make_message(chat_id=100, message_id=5, from_user=None)
    assert await MessageListener()._extract_key(msg) == ListenerKey(100, None, 5)


@pytest.mark.parametrize(
    "overrides",
    [
        {"outgoing": True},
        {"service": True},
        {"empty": True},
        {"edit_date": datetime(2024, 1, 1)},
        {"edit_hidden": True},
        {"chat": None},
    ],
)
async def test_extract_key_is_none_for_an_unlistenable_message(overrides: dict[str, Any]) -> None:
    assert await MessageListener()._extract_key(make_message(**overrides)) is None


async def test_extract_key_is_none_for_own_messages() -> None:
    msg = make_message()
    msg.from_user.is_self = True
    assert await MessageListener()._extract_key(msg) is None
