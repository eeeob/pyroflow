"""Tests for ``MessageListener``: listenability and key extraction."""

from __future__ import annotations as _annotations

import logging
from datetime import datetime
from typing import Any, TYPE_CHECKING

import pytest
from pyrogram import filters

from pyroflow import CallbackQueryListener, MessageListener
from pyroflow.errors import ListenerTimeout
from pyroflow.models import ListenerKey

from ..conftest import make_message

if TYPE_CHECKING:
    from pyroflow.types import Message


# --- class / __init__ --------------------------------------------------------


def test_init_defaults_to_builtin_key_functions() -> None:
    lis = MessageListener()
    assert lis.extract_key_func == lis._extract_key


def test_init_keeps_given_functions_and_forwards_kwargs() -> None:
    def extract_key(update: Message) -> ListenerKey:
        return ListenerKey(1)

    lis = MessageListener(extract_key_func=extract_key, timeout=3)
    assert lis.extract_key_func is extract_key
    assert lis.timeout == 3


# --- the single-update warning ----------------------------------------------------


def test_message_id_names_one_update() -> None:
    assert MessageListener._message_id_names_one_update is True


@pytest.mark.parametrize(
    ("listener_cls", "message_id", "strict", "warned"),
    [
        (MessageListener, 5, False, True),
        (MessageListener, 5, True, False),
        (MessageListener, None, False, False),
        (CallbackQueryListener, 5, False, False),
    ],
)
async def test_listen_warns_of_a_wait_a_rejected_message_leaves_open(
    caplog: pytest.LogCaptureFixture,
    listener_cls: type[MessageListener | CallbackQueryListener],
    message_id: int | None,
    strict: bool,
    warned: bool,
) -> None:
    lis = listener_cls()

    with caplog.at_level(logging.WARNING):
        with pytest.raises(ListenerTimeout):
            await lis.listen(1, 2, message_id, filters=filters.text, strict=strict, timeout=0.001)

    assert ("waits for a single update with a non-strict filter" in caplog.text) is warned


# --- _is_listenable -------------------------------------------------------------


async def test_is_listenable_accepts_incoming_message() -> None:
    assert await MessageListener()._is_listenable(make_message()) is True


async def test_is_listenable_accepts_message_without_sender() -> None:
    assert await MessageListener()._is_listenable(make_message(from_user=None)) is True


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
async def test_is_listenable_rejects(overrides: dict[str, Any]) -> None:
    assert await MessageListener()._is_listenable(make_message(**overrides)) is False


async def test_is_listenable_rejects_own_messages() -> None:
    msg = make_message()
    msg.from_user.is_self = True
    assert await MessageListener()._is_listenable(msg) is False


# --- _extract_key -----------------------------------------------------------------


async def test_extract_key_uses_chat_sender_and_id() -> None:
    msg = make_message(chat_id=-100, user_id=9, message_id=42)
    assert await MessageListener()._extract_key(msg) == ListenerKey(-100, 9, 42)


async def test_extract_key_without_sender_has_no_user() -> None:
    msg = make_message(chat_id=100, message_id=5, from_user=None)
    assert await MessageListener()._extract_key(msg) == ListenerKey(100, None, 5)


async def test_extract_key_is_none_for_an_unlistenable_message() -> None:
    assert await MessageListener()._extract_key(make_message(outgoing=True)) is None
