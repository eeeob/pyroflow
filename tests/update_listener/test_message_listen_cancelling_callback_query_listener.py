"""Tests for `MessageListenCancellingCallbackQueryListener`: the message listen a press cancels."""

from __future__ import annotations as _annotations

import asyncio
from typing import Any, TYPE_CHECKING

import pytest

import pyroflow.update_listener.message_listen_cancelling_callback_query_listener as module
from pyroflow import (
    MessageListenCancellingCallbackQueryListener,
    CallbackQueryListener,
    MessageListener,
)
from pyroflow.enums import MessageListenCancelPolicy, MessageListenCancelScope
from pyroflow.errors import ListenerCancelled
from pyroflow.models import ListenerContext, ListenerKey
from pyroflow.types import Message

from ..conftest import make_callback_query

if TYPE_CHECKING:
    from pyroflow.update_listener import UpdateListener


class _FakeClient:
    """Stands in for a `Client`: only `listeners` is used."""

    def __init__(self, message_listen: MessageListener | None) -> None:
        self.listeners = {} if message_listen is None else {Message: message_listen}


async def _listen(
    lis: MessageListener, *key: int | None, prompt_id: int | None = None
) -> asyncio.Task:
    task = asyncio.create_task(lis.listen(*key, context=ListenerContext(message_id=prompt_id)))
    for _ in range(10):
        if ListenerKey(*key) in lis.listeners:
            break
        await asyncio.sleep(0)
    assert ListenerKey(*key) in lis.listeners
    return task


async def _stop(lis: UpdateListener[Any], *tasks: asyncio.Task) -> None:
    await lis.stop()
    await asyncio.gather(*tasks, return_exceptions=True)


# --- class -------------------------------------------------------------------------


def test_module_exports() -> None:
    assert module.__all__ == ("MessageListenCancellingCallbackQueryListener",)


def test_is_a_callback_query_listener() -> None:
    assert issubclass(MessageListenCancellingCallbackQueryListener, CallbackQueryListener)


def test_init_defaults() -> None:
    lis = MessageListenCancellingCallbackQueryListener()
    assert lis.cancel_policy is MessageListenCancelPolicy.UNRESOLVED
    assert lis.cancel_scope is MessageListenCancelScope.ALL
    assert lis.extract_key_func == lis._extract_key


def test_init_stores_its_arguments_and_forwards_the_rest() -> None:
    lis = MessageListenCancellingCallbackQueryListener(
        cancel_policy=MessageListenCancelPolicy.ALWAYS,
        cancel_scope=MessageListenCancelScope.FIRST,
        timeout=3,
    )
    assert lis.cancel_policy is MessageListenCancelPolicy.ALWAYS
    assert lis.cancel_scope is MessageListenCancelScope.FIRST
    assert lis.timeout == 3


async def test_cancel_message_listen_cancels_every_wait_tied_to_the_pressed_message() -> None:
    mlis = MessageListener()
    specific = await _listen(mlis, 100, 7, prompt_id=5)
    chat_wide = await _listen(mlis, 100, prompt_id=5)
    cbq = make_callback_query(_client=_FakeClient(mlis))

    MessageListenCancellingCallbackQueryListener()._cancel_message_listen(cbq)

    assert mlis.listeners == {}
    for task in (specific, chat_wide):
        with pytest.raises(ListenerCancelled):
            await task


async def test_cancel_message_listen_with_first_scope_cancels_only_the_most_specific() -> None:
    mlis = MessageListener()
    specific = await _listen(mlis, 100, 7, prompt_id=5)
    chat_wide = await _listen(mlis, 100, prompt_id=5)
    cbq = make_callback_query(_client=_FakeClient(mlis))
    lis = MessageListenCancellingCallbackQueryListener(cancel_scope=MessageListenCancelScope.FIRST)

    lis._cancel_message_listen(cbq)

    assert list(mlis.listeners) == [ListenerKey(100)]
    with pytest.raises(ListenerCancelled):
        await specific
    await _stop(mlis, chat_wide)


async def test_cancel_message_listen_does_not_depend_on_extract_key() -> None:
    mlis = MessageListener()
    task = await _listen(mlis, 100, 7, prompt_id=5)
    cbq = make_callback_query(_client=_FakeClient(mlis))
    lis = MessageListenCancellingCallbackQueryListener(extract_key_func=lambda update: None)

    lis._cancel_message_listen(cbq)

    with pytest.raises(ListenerCancelled):
        await task


# --- _cancel_message_listen ---------------------------------------------------------


async def test_cancel_message_listen_without_message_never_touches_the_client() -> None:
    # `_client=None` proves the early return never reaches `message_listen`.
    cbq = make_callback_query(message=None, _client=None)
    MessageListenCancellingCallbackQueryListener()._cancel_message_listen(cbq)


async def test_cancel_message_listen_without_message_id_cancels_nothing() -> None:
    mlis = MessageListener()
    task = await _listen(mlis, 100, 7, 5, prompt_id=None)
    cbq = make_callback_query(_client=_FakeClient(mlis))
    cbq.message.id = None

    MessageListenCancellingCallbackQueryListener()._cancel_message_listen(cbq)

    assert ListenerKey(100, 7, 5) in mlis.listeners
    await _stop(mlis, task)


async def test_cancel_message_listen_without_message_listener_does_nothing() -> None:
    cbq = make_callback_query(_client=_FakeClient(None))
    MessageListenCancellingCallbackQueryListener()._cancel_message_listen(cbq)


async def test_cancel_message_listen_cancels_message_listener_waiting_on_this_message() -> None:
    mlis = MessageListener()
    task = await _listen(mlis, 100, 7, prompt_id=5)
    cbq = make_callback_query(_client=_FakeClient(mlis))

    MessageListenCancellingCallbackQueryListener()._cancel_message_listen(cbq)

    assert ListenerKey(100, 7) not in mlis.listeners
    with pytest.raises(ListenerCancelled):
        await task


async def test_cancel_message_listen_reaches_chat_only_message_listener() -> None:
    mlis = MessageListener()
    task = await _listen(mlis, 100, prompt_id=5)
    cbq = make_callback_query(_client=_FakeClient(mlis))

    MessageListenCancellingCallbackQueryListener()._cancel_message_listen(cbq)

    with pytest.raises(ListenerCancelled):
        await task


@pytest.mark.parametrize("prompt_id", [6, None])
async def test_cancel_message_listen_keeps_listener_for_other_message(
    prompt_id: int | None,
) -> None:
    mlis = MessageListener()
    task = await _listen(mlis, 100, 7, prompt_id=prompt_id)
    cbq = make_callback_query(_client=_FakeClient(mlis))

    MessageListenCancellingCallbackQueryListener()._cancel_message_listen(cbq)

    assert ListenerKey(100, 7) in mlis.listeners
    assert not task.done()
    await _stop(mlis, task)


async def test_cancel_message_listen_picks_the_listener_of_the_pressed_prompt() -> None:
    mlis = MessageListener()
    specific = await _listen(mlis, 100, 7, prompt_id=99)
    chat_wide = await _listen(mlis, 100, prompt_id=5)
    cbq = make_callback_query(_client=_FakeClient(mlis))

    MessageListenCancellingCallbackQueryListener()._cancel_message_listen(cbq)

    assert ListenerKey(100, 7) in mlis.listeners
    with pytest.raises(ListenerCancelled):
        await chat_wide
    await _stop(mlis, specific)


async def test_cancel_message_listen_leaves_an_ask_aimed_at_another_user() -> None:
    mlis = MessageListener()
    task = await _listen(mlis, 100, 8, prompt_id=5)
    cbq = make_callback_query(_client=_FakeClient(mlis))

    MessageListenCancellingCallbackQueryListener()._cancel_message_listen(cbq)

    assert not task.done()
    await _stop(mlis, task)


@pytest.mark.parametrize(
    ("policy", "taken", "cancelled"),
    [
        (MessageListenCancelPolicy.UNRESOLVED, False, True),
        (MessageListenCancelPolicy.UNRESOLVED, True, False),
        (MessageListenCancelPolicy.RESOLVED, False, False),
        (MessageListenCancelPolicy.RESOLVED, True, True),
        (MessageListenCancelPolicy.ALWAYS, False, True),
        (MessageListenCancelPolicy.ALWAYS, True, True),
    ],
)
async def test_resolve_cancels_the_message_listen_as_cancel_policy_says(
    policy: MessageListenCancelPolicy, taken: bool, cancelled: bool
) -> None:
    mlis = MessageListener()
    message_waiter = await _listen(mlis, 100, 7, prompt_id=5)
    clis = MessageListenCancellingCallbackQueryListener(cancel_policy=policy)
    # Waiting for the presser takes the press; waiting for another user leaves it untaken.
    callback_waiter = asyncio.create_task(clis.listen(100, 7 if taken else 8))
    await asyncio.sleep(0)
    cbq = make_callback_query(_client=_FakeClient(mlis))

    assert await clis.resolve(cbq) is taken

    assert (ListenerKey(100, 7) not in mlis.listeners) is cancelled
    if cancelled:
        with pytest.raises(ListenerCancelled):
            await message_waiter
    await _stop(clis, callback_waiter)
    await _stop(mlis, message_waiter)
