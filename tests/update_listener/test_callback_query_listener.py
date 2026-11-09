"""Tests for `CallbackQueryListener`: its defaults, `listen` and key extraction."""

from __future__ import annotations as _annotations

import asyncio
from typing import TYPE_CHECKING


import pyroflow.update_listener.callback_query_listener as callback_query_listener_module
from pyroflow import CallbackQueryListener
from pyroflow.models import CallbackQueryKey, ListenerContext

from ..conftest import make_callback_query

if TYPE_CHECKING:
    from pyroflow.types import CallbackQuery


# --- class / __init__ --------------------------------------------------------


def test_module_exports() -> None:
    assert callback_query_listener_module.__all__ == ("CallbackQueryListener",)


def test_key_type_is_callback_query_key() -> None:
    assert CallbackQueryListener.__key_type__ is CallbackQueryKey


def test_init_defaults_to_from_update() -> None:
    lis = CallbackQueryListener()

    assert lis.extract_key_func == CallbackQueryKey.from_update
    assert lis.extract_key(make_callback_query(-100, 9, 42)) == CallbackQueryKey(-100, 9, 42)
    assert lis.on_error_func is None


def test_init_keeps_a_given_function_and_forwards_kwargs() -> None:
    def extract_key(update: CallbackQuery) -> CallbackQueryKey:
        return CallbackQueryKey(1)

    lis = CallbackQueryListener(extract_key_func=extract_key, timeout=3)
    assert lis.extract_key_func is extract_key
    assert lis.timeout == 3


# --- listen -----------------------------------------------------------------------


async def test_listen_waits_on_its_key() -> None:
    lis = CallbackQueryListener()
    context = ListenerContext(step=1)
    task = asyncio.ensure_future(
        lis.listen(CallbackQueryKey(chat_id=1, user_id=2, message_id=3), context=context)
    )
    await asyncio.sleep(0)
    try:
        assert lis.listeners[CallbackQueryKey(1, 2, 3)].context is context
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


async def test_listen_on_ephemeral_takes_a_press_on_an_ephemeral_message() -> None:
    lis = CallbackQueryListener()
    task = asyncio.ensure_future(
        lis.listen(CallbackQueryKey(chat_id=100, user_id=7, ephemeral=True))
    )
    await asyncio.sleep(0)
    regular = make_callback_query(message_id=5)
    ephemeral = make_callback_query(message_id=0)
    ephemeral.message.ephemeral_message_id = 4

    assert await lis.resolve(regular) is False
    assert await lis.resolve(ephemeral) is True
    assert await task is ephemeral


async def test_listen_on_a_message_takes_only_a_press_on_it() -> None:
    lis = CallbackQueryListener()
    task = asyncio.ensure_future(lis.listen(CallbackQueryKey(chat_id=100, message_id=5)))
    await asyncio.sleep(0)

    assert await lis.resolve(make_callback_query(message_id=6)) is False
    press = make_callback_query(user_id=99, message_id=5)
    assert await lis.resolve(press) is True
    assert await task is press


async def test_listen_on_an_inline_message_takes_only_a_press_on_it() -> None:
    lis = CallbackQueryListener()
    task = asyncio.ensure_future(lis.listen(CallbackQueryKey(inline_message_id="im")))
    await asyncio.sleep(0)

    assert await lis.resolve(make_callback_query(message=None, inline_message_id="other")) is False
    assert await lis.resolve(make_callback_query()) is False
    press = make_callback_query(user_id=99, message=None, inline_message_id="im")
    assert await lis.resolve(press) is True
    assert await task is press


async def test_listen_on_an_inline_message_for_a_user_skips_other_users() -> None:
    lis = CallbackQueryListener()
    task = asyncio.ensure_future(lis.listen(CallbackQueryKey(user_id=7, inline_message_id="im")))
    await asyncio.sleep(0)

    assert (
        await lis.resolve(make_callback_query(user_id=8, message=None, inline_message_id="im"))
        is False
    )
    press = make_callback_query(user_id=7, message=None, inline_message_id="im")
    assert await lis.resolve(press) is True
    assert await task is press


async def test_listen_for_a_user_takes_their_inline_press() -> None:
    lis = CallbackQueryListener()
    task = asyncio.ensure_future(lis.listen(CallbackQueryKey(user_id=7)))
    await asyncio.sleep(0)
    press = make_callback_query(user_id=7, message=None, inline_message_id="im")

    assert await lis.resolve(press) is True
    assert await task is press


async def test_listen_in_a_private_chat_skips_an_inline_press() -> None:
    lis = CallbackQueryListener()
    task = asyncio.ensure_future(lis.listen(CallbackQueryKey(chat_id=7)))
    await asyncio.sleep(0)

    try:
        press = make_callback_query(user_id=7, message=None, inline_message_id="im")
        assert await lis.resolve(press) is False
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


def test_call_is_listen() -> None:
    assert CallbackQueryListener.__call__ is CallbackQueryListener.listen


# --- extract_key -----------------------------------------------------------------


def test_extract_key_uses_message_chat_presser_and_message_id() -> None:
    cbq = make_callback_query(chat_id=-100, user_id=9, message_id=42)
    assert CallbackQueryListener().extract_key(cbq) == CallbackQueryKey(-100, 9, 42)


def test_extract_key_is_none_for_a_callback_without_message() -> None:
    assert CallbackQueryListener().extract_key(make_callback_query(message=None)) is None


def test_extract_key_marks_a_press_on_an_ephemeral_message() -> None:
    update = make_callback_query(message_id=0)
    update.message.ephemeral_message_id = 4

    key = CallbackQueryListener().extract_key(update)

    assert key == CallbackQueryKey(100, 7, ephemeral=True)
