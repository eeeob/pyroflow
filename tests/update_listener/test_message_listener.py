"""Tests for ``MessageListener``: its key, ``listen`` and key extraction."""

from __future__ import annotations as _annotations

import asyncio
from datetime import datetime
from typing import Any, TYPE_CHECKING

import pytest

import pyroflow.update_listener.message_listener as message_listener_module
from pyroflow import MessageListener
from pyroflow.errors import ListenerTimeout
from pyroflow.models import ListenerContext, MessageKey

from ..conftest import make_message

if TYPE_CHECKING:
    from pyroflow.types import Message


# --- class / __init__ --------------------------------------------------------


def test_module_exports() -> None:
    assert message_listener_module.__all__ == ("MessageListener",)


def test_key_type_is_message_key() -> None:
    assert MessageListener.__key_type__ is MessageKey


def test_init_defaults_to_the_builtin_key_function() -> None:
    lis = MessageListener()
    assert lis.extract_key_func == lis._extract_key


def test_init_keeps_a_given_function_and_forwards_kwargs() -> None:
    def extract_key(update: Message) -> MessageKey:
        return MessageKey(1)

    lis = MessageListener(extract_key_func=extract_key, timeout=3)
    assert lis.extract_key_func is extract_key
    assert lis.timeout == 3


# --- listen -----------------------------------------------------------------------


async def test_listen_waits_on_the_key_of_its_fields() -> None:
    lis = MessageListener()
    context = ListenerContext(step=1)
    task = asyncio.ensure_future(
        lis.listen(
            chat_id=1,
            user_id=2,
            message_thread_id=3,
            direct_messages_topic_id=4,
            context=context,
            strict=True,
        )
    )
    await asyncio.sleep(0)
    try:
        model = lis.listeners[MessageKey(1, 2, 3, 4)]
        assert model.context is context
        assert model.strict is True
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


async def test_listen_takes_the_key_fields_by_position() -> None:
    lis = MessageListener()
    task = asyncio.ensure_future(lis.listen(1, 2, 3, 4))
    await asyncio.sleep(0)
    try:
        assert MessageKey(1, 2, 3, 4) in lis.listeners
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


async def test_listen_on_ephemeral_waits_on_an_ephemeral_key() -> None:
    lis = MessageListener()
    task = asyncio.ensure_future(lis.listen(chat_id=1, user_id=2, ephemeral=True))
    await asyncio.sleep(0)
    try:
        assert list(lis.listeners) == [MessageKey(1, 2, ephemeral=True)]
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


async def test_listen_on_ephemeral_in_a_chat_takes_a_message_without_a_sender() -> None:
    lis = MessageListener()
    task = asyncio.ensure_future(lis.listen(chat_id=100, ephemeral=True))
    await asyncio.sleep(0)
    update = make_message(message_id=0, ephemeral_message_id=4, from_user=None)

    assert await lis.resolve(update) is True
    assert await task is update


async def test_listen_for_a_user_takes_them_in_any_chat() -> None:
    lis = MessageListener()
    task = asyncio.ensure_future(lis.listen(user_id=7))
    await asyncio.sleep(0)
    in_group = make_message(chat_id=-100, user_id=7)

    assert await lis.resolve(make_message(chat_id=-100, user_id=8)) is False
    assert await lis.resolve(in_group) is True
    assert await task is in_group


async def test_listen_in_a_private_chat_takes_only_that_chat() -> None:
    lis = MessageListener()
    task = asyncio.ensure_future(lis.listen(chat_id=7))
    await asyncio.sleep(0)
    private = make_message(chat_id=7, user_id=7)

    assert await lis.resolve(make_message(chat_id=-100, user_id=7)) is False
    assert await lis.resolve(private) is True
    assert await task is private


async def test_listen_passes_the_timeout_on() -> None:
    with pytest.raises(ListenerTimeout) as exc:
        await MessageListener().listen(user_id=2, timeout=0.01)

    assert exc.value.value == MessageKey(user_id=2)


async def test_listen_in_a_topic_takes_only_a_message_of_that_topic() -> None:
    lis = MessageListener()
    task = asyncio.ensure_future(lis.listen(chat_id=100, message_thread_id=3))
    await asyncio.sleep(0)

    assert await lis.resolve(make_message(100, message_thread_id=4)) is False
    in_topic = make_message(100, message_thread_id=3)
    assert await lis.resolve(in_topic) is True
    assert await task is in_topic


async def test_listen_in_a_direct_messages_topic_takes_only_a_message_of_that_topic() -> None:
    lis = MessageListener()
    task = asyncio.ensure_future(lis.listen(chat_id=100, direct_messages_topic_id=3))
    await asyncio.sleep(0)

    assert await lis.resolve(make_message(100)) is False
    in_topic = make_message(100, direct_messages_topic_id=3)
    assert await lis.resolve(in_topic) is True
    assert await task is in_topic


def test_call_is_listen() -> None:
    assert MessageListener.__call__ is MessageListener.listen


# --- _extract_key -----------------------------------------------------------------


def test_extract_key_uses_message_key_from_message() -> None:
    msg = make_message(chat_id=-100, user_id=9, message_id=42, message_thread_id=3)
    assert MessageListener()._extract_key(msg) == MessageKey(-100, 9, 3)


def test_extract_key_without_sender_has_no_user() -> None:
    msg = make_message(chat_id=100, message_id=5, from_user=None)
    assert MessageListener()._extract_key(msg) == MessageKey(100)


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
def test_extract_key_is_none_for_an_unlistenable_message(overrides: dict[str, Any]) -> None:
    assert MessageListener()._extract_key(make_message(**overrides)) is None


def test_extract_key_is_none_for_own_messages() -> None:
    msg = make_message()
    msg.from_user.is_self = True
    assert MessageListener()._extract_key(msg) is None


def test_extract_key_marks_an_ephemeral_message() -> None:
    update = make_message(message_id=0, ephemeral_message_id=4)

    assert MessageListener()._extract_key(update) == MessageKey(100, 7, ephemeral=True)


def test_extract_key_keys_an_ephemeral_message_without_a_sender() -> None:
    update = make_message(message_id=0, ephemeral_message_id=4, from_user=None)

    assert MessageListener()._extract_key(update) == MessageKey(100, None, ephemeral=True)
