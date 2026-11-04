"""Tests for ``CallbackQueryListener``: listenability, key extraction and the ask a press cancels."""

from __future__ import annotations as _annotations

import asyncio
from typing import Any, TYPE_CHECKING

import pytest

from pyroflow import CallbackQueryListener, MessageListener
from pyroflow.constants import ASK_MESSAGE_ID_META_KEY
from pyroflow.errors import ListenerCancelled
from pyroflow.models import ListenerKey
from pyroflow.types import Message

from ..conftest import make_callback_query

if TYPE_CHECKING:
    from pyroflow.types import CallbackQuery
    from pyroflow.update_listener import UpdateListener


class _FakeClient:
    """Stands in for a `Client`: only `listeners` is used."""

    def __init__(self, message_listen: MessageListener | None) -> None:
        self.listeners = {} if message_listen is None else {Message: message_listen}


async def _listen(
    lis: MessageListener, *key: int | None, prompt_id: int | None = None
) -> asyncio.Task:
    meta = None if prompt_id is None else {ASK_MESSAGE_ID_META_KEY: prompt_id}
    task = asyncio.create_task(lis.listen(*key, meta=meta))
    for _ in range(10):
        if ListenerKey(*key) in lis.listeners:
            break
        await asyncio.sleep(0)
    assert ListenerKey(*key) in lis.listeners
    return task


async def _stop(lis: UpdateListener[Any], *tasks: asyncio.Task) -> None:
    await lis.stop()
    await asyncio.gather(*tasks, return_exceptions=True)


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


async def test_cancel_prompted_ask_does_not_depend_on_extract_key() -> None:
    mlis = MessageListener()
    task = await _listen(mlis, 100, 7, prompt_id=5)
    cbq = make_callback_query(_client=_FakeClient(mlis))
    lis = CallbackQueryListener(extract_key_func=lambda update: None)

    lis._cancel_prompted_ask(cbq)

    with pytest.raises(ListenerCancelled):
        await task


# --- _cancel_prompted_ask ---------------------------------------------------------


async def test_cancel_prompted_ask_without_message_never_touches_the_client() -> None:
    # `_client=None` proves the early return never reaches `message_listen`.
    cbq = make_callback_query(message=None, _client=None)
    CallbackQueryListener()._cancel_prompted_ask(cbq)


async def test_cancel_prompted_ask_without_message_id_cancels_nothing() -> None:
    mlis = MessageListener()
    task = await _listen(mlis, 100, 7, 5, prompt_id=None)
    cbq = make_callback_query(_client=_FakeClient(mlis))
    cbq.message.id = None

    CallbackQueryListener()._cancel_prompted_ask(cbq)

    assert ListenerKey(100, 7, 5) in mlis.listeners
    await _stop(mlis, task)


async def test_cancel_prompted_ask_without_message_listener_does_nothing() -> None:
    cbq = make_callback_query(_client=_FakeClient(None))
    CallbackQueryListener()._cancel_prompted_ask(cbq)


async def test_cancel_prompted_ask_cancels_message_listener_waiting_on_this_message() -> None:
    mlis = MessageListener()
    task = await _listen(mlis, 100, 7, prompt_id=5)
    cbq = make_callback_query(_client=_FakeClient(mlis))

    CallbackQueryListener()._cancel_prompted_ask(cbq)

    assert ListenerKey(100, 7) not in mlis.listeners
    with pytest.raises(ListenerCancelled):
        await task


async def test_cancel_prompted_ask_reaches_chat_only_message_listener() -> None:
    mlis = MessageListener()
    task = await _listen(mlis, 100, prompt_id=5)
    cbq = make_callback_query(_client=_FakeClient(mlis))

    CallbackQueryListener()._cancel_prompted_ask(cbq)

    with pytest.raises(ListenerCancelled):
        await task


@pytest.mark.parametrize("prompt_id", [6, None])
async def test_cancel_prompted_ask_keeps_listener_for_other_message(prompt_id: int | None) -> None:
    mlis = MessageListener()
    task = await _listen(mlis, 100, 7, prompt_id=prompt_id)
    cbq = make_callback_query(_client=_FakeClient(mlis))

    CallbackQueryListener()._cancel_prompted_ask(cbq)

    assert ListenerKey(100, 7) in mlis.listeners
    assert not task.done()
    await _stop(mlis, task)


async def test_cancel_prompted_ask_picks_the_listener_of_the_pressed_prompt() -> None:
    mlis = MessageListener()
    specific = await _listen(mlis, 100, 7, prompt_id=99)
    chat_wide = await _listen(mlis, 100, prompt_id=5)
    cbq = make_callback_query(_client=_FakeClient(mlis))

    CallbackQueryListener()._cancel_prompted_ask(cbq)

    assert ListenerKey(100, 7) in mlis.listeners
    with pytest.raises(ListenerCancelled):
        await chat_wide
    await _stop(mlis, specific)


async def test_cancel_prompted_ask_leaves_an_ask_aimed_at_another_user() -> None:
    mlis = MessageListener()
    task = await _listen(mlis, 100, 8, prompt_id=5)
    cbq = make_callback_query(_client=_FakeClient(mlis))

    CallbackQueryListener()._cancel_prompted_ask(cbq)

    assert not task.done()
    await _stop(mlis, task)


async def test_resolve_unmatched_callback_cancels_message_listener() -> None:
    mlis = MessageListener()
    message_waiter = await _listen(mlis, 100, 7, prompt_id=5)
    clis = CallbackQueryListener()
    # Another user's callback listener keeps `resolve` from short-circuiting.
    callback_waiter = asyncio.create_task(clis.listen(100, 8))
    await asyncio.sleep(0)
    cbq = make_callback_query(_client=_FakeClient(mlis))

    assert await clis.resolve(cbq) is False

    with pytest.raises(ListenerCancelled):
        await message_waiter
    assert not callback_waiter.done()
    await _stop(clis, callback_waiter)


async def test_resolve_resolved_callback_leaves_the_message_listener() -> None:
    mlis = MessageListener()
    message_waiter = await _listen(mlis, 100, 7, prompt_id=5)
    clis = CallbackQueryListener()
    callback_waiter = asyncio.create_task(clis.listen(100, 7))
    await asyncio.sleep(0)
    cbq = make_callback_query(_client=_FakeClient(mlis))

    assert await clis.resolve(cbq) is True

    assert await callback_waiter is cbq
    assert not message_waiter.done()
    await _stop(mlis, message_waiter)
