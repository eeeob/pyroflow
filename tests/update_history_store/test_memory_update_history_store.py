"""Tests for the in-memory history store: TTL, per-key capacity and key-space
bounds."""

from __future__ import annotations as _annotations

import time

from cachetools import TTLCache
from pyrogram.types import Message
from pytrove.enums import TimeUnit

from pyroflow.models import UpdateRecord
from pyroflow.update_history_store.memory_update_history_store import (
    MemoryUpdateHistoryStore,
)
from pyroflow.update_history_store.update_history_store import UpdateHistoryStore


def _store(ttl: float = 100, max_history_len: int = 2) -> MemoryUpdateHistoryStore:
    return MemoryUpdateHistoryStore(Message, ttl=ttl, max_history_len=max_history_len)


# --- __init__ ------------------------------------------------------------------------------


def test_init_defaults() -> None:
    store = MemoryUpdateHistoryStore(Message)
    assert isinstance(store, UpdateHistoryStore)
    assert store.update_type is Message
    assert store.ttl == TimeUnit.DAY / 2 == 43200
    assert store.max_history_len == 2
    assert store.histories.maxsize == 1000
    assert store.histories.ttl == store.ttl
    assert len(store.histories) == 0


def test_init_custom_bounds_reach_the_key_cache() -> None:
    store = MemoryUpdateHistoryStore(Message, ttl=30, max_history_len=5, max_keys=7)
    assert (store.ttl, store.max_history_len) == (30, 5)
    assert (store.histories.maxsize, store.histories.ttl) == (7, 30)


# --- _expires_at / _is_expired -------------------------------------------------------------


def test_expires_at_is_created_at_plus_ttl() -> None:
    store = _store(ttl=10)
    assert store._expires_at(UpdateRecord(handler="h", created_at=1000)) == 1010


def test_is_expired_at_explicit_now_includes_the_boundary() -> None:
    store = _store(ttl=10)
    record = UpdateRecord(handler="h", created_at=1000)
    assert store._is_expired(record, 1009.999) is False
    assert store._is_expired(record, 1010) is True
    assert store._is_expired(record, 2000) is True


# --- _clean_up ----------------------------------------------------------------------------


def test_clean_up_pops_expired_records_in_place() -> None:
    store = _store(ttl=10)
    older = UpdateRecord(handler="older", created_at=-5)
    old = UpdateRecord(handler="old", created_at=0)
    fresh = UpdateRecord(handler="fresh", created_at=100)
    heap = [older, old, fresh]
    result = store._clean_up(heap, now=105)
    assert result is heap
    assert [r.handler for r in heap] == ["fresh"]


def test_clean_up_defaults_to_the_current_time() -> None:
    store = _store(ttl=10)
    now = time.time()
    heap = [UpdateRecord(handler="old", created_at=now - 20), UpdateRecord(handler="new")]
    assert [r.handler for r in store._clean_up(heap)] == ["new"]


# --- _update / update ----------------------------------------------------------------------


def test_update_creates_the_key() -> None:
    store = _store()
    store._update("k", UpdateRecord(handler="h"))
    assert [r.handler for r in store.histories["k"]] == ["h"]


async def test_update_appends_to_existing_key_and_trims_oldest() -> None:
    store = _store(max_history_len=2)
    now = time.time()
    await store.update("k", UpdateRecord(handler="h1", created_at=now - 2))
    await store.update("k", UpdateRecord(handler="h2", created_at=now - 1))
    await store.update("k", UpdateRecord(handler="h3", created_at=now))
    assert [r.handler for r in await store.get("k")] == ["h2", "h3"]


async def test_update_with_equal_timestamps_keeps_the_last_created() -> None:
    store = _store(max_history_len=2)
    now = time.time()
    records = [UpdateRecord(handler=h, created_at=now) for h in ("a", "b", "c")]
    await store.update("k", *records)
    assert [r.handler for r in await store.get("k")] == ["b", "c"]


async def test_update_with_only_expired_records_drops_the_key() -> None:
    store = _store(ttl=10)
    await store.update("k", UpdateRecord(handler="old", created_at=time.time() - 100))
    assert "k" not in store.histories


async def test_update_expired_records_free_room_for_new_ones() -> None:
    store = _store(ttl=10, max_history_len=2)
    now = time.time()
    await store.update(
        "k",
        UpdateRecord(handler="old", created_at=now - 100),
        UpdateRecord(handler="new", created_at=now),
    )
    assert [r.handler for r in store.histories["k"]] == ["new"]


async def test_update_restarts_the_key_ttl() -> None:
    store = _store(ttl=100)
    clock = [0.0]
    store.histories = TTLCache(maxsize=10, ttl=100, timer=lambda: clock[0])
    first, second = UpdateRecord(handler="a"), UpdateRecord(handler="b")

    await store.update(("k",), first)
    clock[0] = 90
    await store.update(("k",), second)
    clock[0] = 150

    assert await store.get(("k",)) == [first, second]


async def test_update_without_records_leaves_no_key() -> None:
    store = _store()
    assert await store.update("k") is None
    assert "k" not in store.histories


async def test_update_evicts_the_least_recently_used_key() -> None:
    store = MemoryUpdateHistoryStore(Message, ttl=100, max_keys=2)
    await store.update("a", UpdateRecord(handler="a"))
    await store.update("b", UpdateRecord(handler="b"))
    await store.get("a")  # touches "a", leaving "b" least recently used
    await store.update("c", UpdateRecord(handler="c"))
    assert set(store.histories) == {"a", "c"}


# --- _get / get ----------------------------------------------------------------------------


async def test_get_missing_key_returns_empty_without_creating_it() -> None:
    store = _store()
    assert await store.get("missing") == []
    assert "missing" not in store.histories


async def test_get_returns_a_sorted_copy() -> None:
    store = _store(max_history_len=3)
    now = time.time()
    await store.update(
        "k",
        UpdateRecord(handler="c", created_at=now),
        UpdateRecord(handler="a", created_at=now - 2),
        UpdateRecord(handler="b", created_at=now - 1),
    )
    records = store._get("k")
    assert [r.handler for r in records] == ["a", "b", "c"]
    records.clear()
    assert len(store.histories["k"]) == 3


async def test_get_drops_records_that_expired_since_the_write() -> None:
    store = _store(ttl=10, max_history_len=3)
    now = time.time()
    store.histories["k"] = [
        UpdateRecord(handler="old", created_at=now - 100),
        UpdateRecord(handler="new", created_at=now),
    ]
    assert [r.handler for r in await store.get("k")] == ["new"]
    assert [r.handler for r in store.histories["k"]] == ["new"]


async def test_get_drops_the_key_once_every_record_expired() -> None:
    store = _store(ttl=10)
    store.histories["k"] = [UpdateRecord(handler="old", created_at=time.time() - 100)]
    assert await store.get("k") == []
    assert "k" not in store.histories


# --- _pop / pop ----------------------------------------------------------------------------


def test_pop_sync_returns_sorted_unexpired_records_and_removes_the_key() -> None:
    store = _store(ttl=10, max_history_len=3)
    now = time.time()
    store.histories["k"] = [
        UpdateRecord(handler="old", created_at=now - 100),
        UpdateRecord(handler="b", created_at=now - 1),
        UpdateRecord(handler="a", created_at=now - 2),
    ]
    assert [r.handler for r in store._pop("k")] == ["a", "b"]
    assert "k" not in store.histories
    assert store._pop("missing") == []


async def test_pop_returns_sorted_unexpired_records_and_removes_the_key() -> None:
    store = _store(ttl=10, max_history_len=3)
    now = time.time()
    # a valid heap: the expired record sits at the front
    store.histories["k"] = [
        UpdateRecord(handler="old", created_at=now - 100),
        UpdateRecord(handler="b", created_at=now - 1),
        UpdateRecord(handler="a", created_at=now - 2),
    ]
    assert [r.handler for r in await store.pop("k")] == ["a", "b"]
    assert "k" not in store.histories


async def test_pop_missing_key_returns_empty() -> None:
    assert await _store().pop("missing") == []


# --- _delete / delete ----------------------------------------------------------------------


async def test_delete_removes_only_the_given_key() -> None:
    store = _store()
    await store.update("a", UpdateRecord(handler="a"))
    await store.update("b", UpdateRecord(handler="b"))
    assert await store.delete("a") is None
    assert set(store.histories) == {"b"}


async def test_delete_missing_key_is_a_no_op() -> None:
    store = _store()
    await store.delete("missing")
    store._delete("missing")
    assert len(store.histories) == 0
