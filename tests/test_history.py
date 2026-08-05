"""Tests for the update-history subsystem.

Covers the in-memory store (TTL, per-key capacity and key-space bounds), the
generic UpdateHistory record/get/pop flow via injected extractors, and the
concrete Message/CallbackQuery histories.
"""

import time

from pyrogram.types import Message

from pyroflow import CallbackQueryHistory, MessageHistory
from pyroflow.models import UpdateRecord
from pyroflow.update_history_store.memory_update_history_store import (
    MemoryUpdateHistoryStore,
)

from .conftest import make_callback_query, make_message


# --- MemoryUpdateHistoryStore ---------------------------------------------


def _store(ttl=100, max_history_len=2):
    return MemoryUpdateHistoryStore(Message, ttl=ttl, max_history_len=max_history_len)


async def test_store_update_and_get_ordered():
    store = _store()
    now = time.time()
    await store.update(
        ("k",),
        UpdateRecord(handler="h1", created_at=now - 2),
        UpdateRecord(handler="h2", created_at=now - 1),
    )
    recs = await store.get(("k",))
    assert [r.handler for r in recs] == ["h1", "h2"]  # oldest → newest


async def test_store_enforces_max_history_len():
    store = _store(max_history_len=2)
    now = time.time()
    await store.update(
        ("k",),
        UpdateRecord(handler="h1", created_at=now - 3),
        UpdateRecord(handler="h2", created_at=now - 2),
        UpdateRecord(handler="h3", created_at=now - 1),
    )
    recs = await store.get(("k",))
    # only the two newest survive
    assert [r.handler for r in recs] == ["h2", "h3"]


async def test_store_drops_expired_records():
    store = _store(ttl=100)
    now = time.time()
    await store.update(("k",), UpdateRecord(handler="old", created_at=now - 1000))
    assert await store.get(("k",)) == []


async def test_store_bounds_the_key_space():
    """Per-record TTL is enforced lazily on access, so it can never reclaim a
    key that is written once and never read again. Without a cap on the key
    space itself, a long-running bot accumulates one entry per conversation
    forever (audit finding H3)."""
    store = MemoryUpdateHistoryStore(
        Message, ttl=3600, max_history_len=2, max_keys=100
    )
    for i in range(5000):
        await store.update((100, 7, i), UpdateRecord(handler="h"))

    assert len(store.histories) <= 100


async def test_store_expires_idle_keys_never_read_again():
    store = MemoryUpdateHistoryStore(Message, ttl=0.05, max_history_len=2)
    for i in range(50):
        await store.update((1, 2, i), UpdateRecord(handler="h"))
    assert len(store.histories) > 0

    time.sleep(0.12)
    assert len(store.histories) == 0, "idle keys must not stay resident forever"


async def test_store_pop_and_delete():
    store = _store()
    await store.update(("k",), UpdateRecord(handler="h1"))
    popped = await store.pop(("k",))
    assert [r.handler for r in popped] == ["h1"]
    assert await store.get(("k",)) == []

    await store.update(("k2",), UpdateRecord(handler="h2"))
    await store.delete(("k2",))
    assert await store.get(("k2",)) == []


# --- Generic UpdateHistory flow (extractor injection) ---------------------


async def test_update_history_record_and_get_with_injected_extractors():
    """The base record→store→get pipeline works when the three extractors
    are supplied — proving the machinery itself is sound (independent of C4)."""
    history = MessageHistory(
        is_recordable_func=lambda u: True,
        extract_key_func=lambda u: (u.chat.id, u.from_user.id),
        extract_data_func=lambda u: u.id,
    )
    await history.start()
    try:
        msg = make_message(100, 7, 5)
        await history.record(msg, handler="H")
        recs = await history.get(msg)
        assert [r.handler for r in recs] == ["H"]
        assert recs[0].data == 5
    finally:
        await history.stop()


async def test_update_history_record_many():
    history = MessageHistory(
        is_recordable_func=lambda u: True,
        extract_key_func=lambda u: (u.chat.id,),
        extract_data_func=lambda u: None,
        store_factory=lambda ut: MemoryUpdateHistoryStore(ut, max_history_len=10),
    )
    await history.start()
    try:
        msg = make_message(100, 7, 5)
        await history.record_many(msg, ["H1", "H2", "H3"])
        recs = await history.get(msg)
        assert [r.handler for r in recs] == ["H1", "H2", "H3"]
    finally:
        await history.stop()


# --- Concrete histories ---------------------------------------------------


async def test_callback_query_history_works_out_of_the_box():
    history = CallbackQueryHistory()
    cbq = make_callback_query(100, 7, 5, data="payload")
    assert await history.is_recordable(cbq) is True
    assert await history.extract_key(cbq) == (100, 7, 5)
    assert await history.extract_data(cbq) == "payload"


async def test_message_history_works_out_of_the_box():
    """C4 fixed: a bare MessageHistory() ships working extractors, matching
    CallbackQueryHistory, so it records without raising NotImplementedError."""
    history = MessageHistory()
    msg = make_message(100, 7, 5, text="hello")
    assert await history.is_recordable(msg) is True
    assert await history.extract_key(msg) == (100, 7, 5)
    assert await history.extract_data(msg) == "hello"


async def test_message_history_records_end_to_end():
    history = MessageHistory()
    await history.start()
    try:
        msg = make_message(100, 7, 5, text="hi")
        await history.record(msg, handler="H")
        recs = await history.get(msg)
        assert [r.handler for r in recs] == ["H"]
        assert recs[0].data == "hi"
    finally:
        await history.stop()
