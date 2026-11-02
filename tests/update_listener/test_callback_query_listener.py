"""Tests for ``CallbackQueryListener``: listenability, key extraction and ``on_unresolved``."""

from __future__ import annotations as _annotations

import asyncio
from typing import Any, TYPE_CHECKING

import pytest

from pyroflow import CallbackQueryListener, MessageListener
from pyroflow.errors import ListenerCancelled, UnresolvedUpdate
from pyroflow.models import ListenerKey

from ..conftest import make_callback_query

if TYPE_CHECKING:
    from pyroflow.types import CallbackQuery
    from pyroflow.update_listener import UpdateListener


class _FakeClient:
    """Stands in for a `Client`: only `message_listen` is used."""

    def __init__(self, message_listen: MessageListener | None) -> None:
        self._message_listen = message_listen

    @property
    def message_listen(self) -> MessageListener:
        if self._message_listen is None:
            msg = "Message"
            raise KeyError(msg)
        return self._message_listen


async def _listen(lis: MessageListener, *key: int | None, meta: Any = None) -> asyncio.Task:
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
    assert lis.is_listenable_func == lis._is_listenable
    assert lis.extract_key_func == lis._extract_key
    assert lis.bypass_func is None


def test_init_keeps_given_functions_and_forwards_kwargs() -> None:
    def is_listenable(update: CallbackQuery) -> bool:
        return False

    def extract_key(update: CallbackQuery) -> ListenerKey:
        return ListenerKey(1)

    lis = CallbackQueryListener(
        is_listenable_func=is_listenable, extract_key_func=extract_key, timeout=3
    )
    assert lis.is_listenable_func is is_listenable
    assert lis.extract_key_func is extract_key
    assert lis.timeout == 3


# --- _is_listenable / _extract_key -------------------------------------------------


async def test_is_listenable_accepts_callback_on_message_in_chat() -> None:
    assert await CallbackQueryListener()._is_listenable(make_callback_query()) is True


async def test_is_listenable_rejects_callback_without_message() -> None:
    cbq = make_callback_query(message=None)
    assert await CallbackQueryListener()._is_listenable(cbq) is False


async def test_is_listenable_rejects_message_without_chat() -> None:
    cbq = make_callback_query()
    cbq.message.chat = None
    assert await CallbackQueryListener()._is_listenable(cbq) is False


async def test_extract_key_uses_message_chat_sender_and_message_id() -> None:
    cbq = make_callback_query(chat_id=-100, user_id=9, message_id=42)
    assert await CallbackQueryListener()._extract_key(cbq) == ListenerKey(-100, 9, 42)


# --- on_unresolved ---------------------------------------------------------------


async def test_on_unresolved_without_message_raises_without_touching_client() -> None:
    # `_client=None` proves the early return never reaches `message_listen`.
    cbq = make_callback_query(message=None, _client=None)
    with pytest.raises(UnresolvedUpdate):
        await CallbackQueryListener().on_unresolved(ListenerKey(100, 7, 5), cbq)


async def test_on_unresolved_without_message_id_cancels_nothing() -> None:
    mlis = MessageListener()
    task = await _listen(mlis, 100, 7, 5, meta={"message_id": None})
    cbq = make_callback_query(_client=_FakeClient(mlis))
    cbq.message.id = None

    with pytest.raises(UnresolvedUpdate):
        await CallbackQueryListener().on_unresolved(ListenerKey(100, 7, 5), cbq)

    assert ListenerKey(100, 7, 5) in mlis.listeners
    await _stop(mlis, task)


async def test_on_unresolved_without_message_listener_raises() -> None:
    cbq = make_callback_query(_client=_FakeClient(None))
    with pytest.raises(UnresolvedUpdate):
        await CallbackQueryListener().on_unresolved(ListenerKey(100, 7, 5), cbq)


async def test_on_unresolved_cancels_message_listener_waiting_on_this_message() -> None:
    mlis = MessageListener()
    task = await _listen(mlis, 100, 7, meta={"message_id": 5})
    cbq = make_callback_query(_client=_FakeClient(mlis))

    with pytest.raises(UnresolvedUpdate):
        await CallbackQueryListener().on_unresolved(ListenerKey(100, 7, 5), cbq)

    assert ListenerKey(100, 7) not in mlis.listeners
    with pytest.raises(ListenerCancelled):
        await task


async def test_on_unresolved_reaches_chat_only_message_listener() -> None:
    mlis = MessageListener()
    task = await _listen(mlis, 100, meta={"message_id": 5})
    cbq = make_callback_query(_client=_FakeClient(mlis))

    with pytest.raises(UnresolvedUpdate):
        await CallbackQueryListener().on_unresolved(ListenerKey(100, 7, 5), cbq)

    with pytest.raises(ListenerCancelled):
        await task


@pytest.mark.parametrize("meta", [{"message_id": 6}, {}, None, [5], "5"])
async def test_on_unresolved_keeps_listener_for_other_message(meta: Any) -> None:
    mlis = MessageListener()
    task = await _listen(mlis, 100, 7, meta=meta)
    cbq = make_callback_query(_client=_FakeClient(mlis))

    with pytest.raises(UnresolvedUpdate):
        await CallbackQueryListener().on_unresolved(ListenerKey(100, 7, 5), cbq)

    assert ListenerKey(100, 7) in mlis.listeners
    assert not task.done()
    await _stop(mlis, task)


async def test_on_unresolved_only_checks_first_matching_message_listener() -> None:
    mlis = MessageListener()
    specific = await _listen(mlis, 100, 7, meta={"message_id": 99})
    chat_wide = await _listen(mlis, 100, meta={"message_id": 5})
    cbq = make_callback_query(_client=_FakeClient(mlis))

    with pytest.raises(UnresolvedUpdate):
        await CallbackQueryListener().on_unresolved(ListenerKey(100, 7, 5), cbq)

    assert ListenerKey(100, 7) in mlis.listeners
    assert ListenerKey(100) in mlis.listeners
    await _stop(mlis, specific, chat_wide)


async def test_resolve_unmatched_callback_cancels_message_listener() -> None:
    mlis = MessageListener()
    message_waiter = await _listen(mlis, 100, 7, meta={"message_id": 5})
    clis = CallbackQueryListener()
    # Another user's callback listener keeps `resolve` from short-circuiting.
    callback_waiter = asyncio.create_task(clis.listen(100, 8))
    await asyncio.sleep(0)
    cbq = make_callback_query(_client=_FakeClient(mlis))

    with pytest.raises(UnresolvedUpdate):
        await clis.resolve(cbq)

    with pytest.raises(ListenerCancelled):
        await message_waiter
    assert not callback_waiter.done()
    await _stop(clis, callback_waiter)
