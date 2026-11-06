"""Tests for `CallbackQueryListener`: its defaults and key extraction."""

from __future__ import annotations as _annotations

from typing import TYPE_CHECKING


from pyroflow import CallbackQueryListener
from pyroflow.enums import ListenMessageId
from pyroflow.models import ListenerKey

from ..conftest import make_callback_query

if TYPE_CHECKING:
    from pyroflow.types import CallbackQuery


# --- class / __init__ --------------------------------------------------------


def test_init_defaults_to_builtin_key_functions() -> None:
    lis = CallbackQueryListener()
    assert lis.extract_key_func == lis._extract_key
    assert lis.on_error_func is None
    assert lis.on_listen_func is None


def test_init_keeps_given_functions_and_forwards_kwargs() -> None:
    def extract_key(update: CallbackQuery) -> ListenerKey:
        return ListenerKey(1)

    lis = CallbackQueryListener(extract_key_func=extract_key, timeout=3)
    assert lis.extract_key_func is extract_key
    assert lis.timeout == 3


# --- _extract_key -----------------------------------------------------------------


async def test_extract_key_uses_message_chat_sender_and_message_id() -> None:
    cbq = make_callback_query(chat_id=-100, user_id=9, message_id=42)
    assert await CallbackQueryListener()._extract_key(cbq) == ListenerKey(-100, 9, 42)


async def test_extract_key_is_none_for_a_callback_without_message() -> None:
    assert await CallbackQueryListener()._extract_key(make_callback_query(message=None)) is None


async def test_extract_key_is_none_for_a_message_without_chat() -> None:
    cbq = make_callback_query()
    cbq.message.chat = None
    assert await CallbackQueryListener()._extract_key(cbq) is None


async def test_extract_key_holds_ephemeral_instead_of_an_ephemeral_messages_id() -> None:
    update = make_callback_query(message_id=0)
    update.message.ephemeral_message_id = 4

    key = await CallbackQueryListener()._extract_key(update)

    assert key == ListenerKey(100, 7, ListenMessageId.EPHEMERAL)
