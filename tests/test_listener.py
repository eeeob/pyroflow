"""Behavioural tests for UpdateListener + MemoryListenerCoordinator.

Covers the listen/resolve/timeout/cancel lifecycle and the duplicate
policies, using the real Message/CallbackQuery listeners with the default
in-memory coordinator (no network).
"""

import asyncio

import pytest

from pyroflow import MessageListener, CallbackQueryListener
from pyroflow.enums import DuplicatePolicy
from pyroflow.errors import (
    ListenerAlreadyExists,
    ListenerCancelled,
    ListenerTimeout,
)
from pyroflow.models import ListenerKey

from .conftest import make_callback_query, make_message


async def _started(listener):
    await listener.start()
    return listener


async def test_message_listener_is_listenable_and_key():
    lis = MessageListener()
    msg = make_message(chat_id=100, user_id=7, message_id=5)
    assert await lis.is_listenable(msg) is True
    assert await lis.extract_key(msg) == ListenerKey(100, 7, 5)


async def test_message_listener_rejects_service_and_self():
    lis = MessageListener()
    assert await lis.is_listenable(make_message(chat_id=100)) is True
    assert await lis.is_listenable(make_message(service=True)) is False
    assert await lis.is_listenable(make_message(outgoing=True)) is False


async def test_listen_then_resolve_returns_update():
    lis = await _started(MessageListener())
    try:
        task = asyncio.ensure_future(lis.listen(100, 7))
        await asyncio.sleep(0.02)
        await lis.resolve(make_message(100, 7, 5))
        got = await asyncio.wait_for(task, 1)
        assert got.id == 5
    finally:
        await lis.stop()


async def test_resolve_matches_less_specific_key():
    """A listener on (chat, user) matches an update with a message id via
    progressive ListenerKey.sub_keys() fallback."""
    lis = await _started(MessageListener())
    try:
        task = asyncio.ensure_future(lis.listen(100))  # chat-only listener
        await asyncio.sleep(0.02)
        await lis.resolve(make_message(100, 7, 5))
        got = await asyncio.wait_for(task, 1)
        assert got.chat.id == 100
    finally:
        await lis.stop()


async def test_resolve_matches_a_message_only_listener():
    """`listen(chat, None, message_id)` — "whoever answers *this* message,
    regardless of who they are" — has always been registrable. Before the
    combination-based sub_keys() it could never be reached: resolution only
    tried prefixes, so (chat, None, message) was never among the candidates
    and the listener sat there until it timed out."""
    lis = await _started(MessageListener())
    try:
        task = asyncio.ensure_future(lis.listen(100, None, 5, timeout=5))
        await asyncio.sleep(0.02)

        # An update from a user the listener never named.
        await lis.resolve(make_message(100, 7, 5))

        got = await asyncio.wait_for(task, 1)
        assert got.id == 5
    finally:
        await lis.stop()


async def test_user_listener_still_outranks_a_message_only_one():
    """Ordering is by specificity, then by field order: a (chat, user)
    listener must keep winning over a (chat, None, message) one, so the new
    rung cannot steal updates from listeners that already worked."""
    lis = await _started(MessageListener())
    try:
        by_user = asyncio.ensure_future(lis.listen(100, 7, timeout=5))
        by_message = asyncio.ensure_future(lis.listen(100, None, 5, timeout=5))
        await asyncio.sleep(0.02)

        await lis.resolve(make_message(100, 7, 5))

        got = await asyncio.wait_for(by_user, 1)
        assert got.id == 5
        assert not by_message.done(), "the less specific listener was consumed"
    finally:
        by_message.cancel()
        await asyncio.gather(by_message, return_exceptions=True)
        await lis.stop()


async def test_listen_timeout_raises():
    lis = await _started(MessageListener())
    try:
        with pytest.raises(ListenerTimeout):
            await lis.listen(200, 7, timeout=0.05)
    finally:
        await lis.stop()


async def test_cancel_raises_listener_cancelled():
    lis = await _started(MessageListener())
    try:
        task = asyncio.ensure_future(lis.listen(100, 7))
        await asyncio.sleep(0.02)
        await lis.cancel(ListenerKey(100, 7))
        with pytest.raises(ListenerCancelled):
            await asyncio.wait_for(task, 1)
    finally:
        await lis.stop()


async def test_duplicate_policy_replace_cancels_previous():
    lis = await _started(MessageListener(duplicate_policy=DuplicatePolicy.REPLACE))
    try:
        first = asyncio.ensure_future(lis.listen(100, 7))
        await asyncio.sleep(0.02)
        second = asyncio.ensure_future(lis.listen(100, 7))
        await asyncio.sleep(0.02)

        with pytest.raises(ListenerCancelled):
            await asyncio.wait_for(first, 1)

        # the replacement is still alive and resolvable
        await lis.resolve(make_message(100, 7, 5))
        got = await asyncio.wait_for(second, 1)
        assert got.id == 5
    finally:
        await lis.stop()


async def test_duplicate_policy_reject_raises():
    lis = await _started(MessageListener(duplicate_policy=DuplicatePolicy.REJECT))
    try:
        first = asyncio.ensure_future(lis.listen(100, 7))
        await asyncio.sleep(0.02)
        with pytest.raises(ListenerAlreadyExists):
            await lis.listen(100, 7)
        await lis.cancel(ListenerKey(100, 7))
        with pytest.raises(ListenerCancelled):
            await asyncio.wait_for(first, 1)
    finally:
        await lis.stop()


async def test_listener_default_timeout_used_when_not_overridden():
    lis = await _started(MessageListener(timeout=0.05))
    try:
        with pytest.raises(ListenerTimeout):
            await lis.listen(300, 7)  # no per-call timeout → falls back to 0.05
    finally:
        await lis.stop()


async def test_callback_listener_is_listenable_and_key():
    lis = CallbackQueryListener()
    cbq = make_callback_query(chat_id=100, user_id=7, message_id=5)
    assert await lis.is_listenable(cbq) is True
    assert await lis.extract_key(cbq) == ListenerKey(100, 7, 5)
