"""Tests for the generic UpdateHistory record/get flow via injected
extractors."""

from __future__ import annotations as _annotations

import threading
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
from typing import Any

import pytest

from pyrogram.types import Message

from pyroflow.models import UpdateRecord
from pyroflow.update_history.update_history import UpdateHistory
from pyroflow.update_history_store.memory_update_history_store import (
    MemoryUpdateHistoryStore,
)
from pyroflow.update_history_store.update_history_store import UpdateHistoryStore

from ..conftest import make_callback_query, make_message


# --- helpers -------------------------------------------------------------------------------


class _SpyStore(UpdateHistoryStore):
    """A store that logs every call and keeps records in a plain dict."""

    def __init__(self, update_type: type[Message], **kw: Any) -> None:
        super().__init__(update_type, **kw)
        self.calls: list[tuple[Any, ...]] = []
        self.data: dict[Any, list[UpdateRecord]] = {}

    async def update(self, key: Any, *records: UpdateRecord) -> None:
        self.calls.append(("update", key, records))
        self.data.setdefault(key, []).extend(records)

    async def get(self, key: Any) -> list[UpdateRecord]:
        self.calls.append(("get", key))
        return list(self.data.get(key, []))

    async def pop(self, key: Any) -> list[UpdateRecord]:
        self.calls.append(("pop", key))
        return self.data.pop(key, [])

    async def delete(self, key: Any) -> None:
        self.calls.append(("delete", key))
        self.data.pop(key, None)

    async def start(self) -> None:
        self.calls.append(("start",))

    async def stop(self) -> None:
        self.calls.append(("stop",))


class _BareHistory(UpdateHistory[Message]):
    __update_type__ = Message


def _history(recordable: bool = True, **kw: Any) -> _BareHistory:
    kw.setdefault("store_factory", _SpyStore)
    kw.setdefault("is_recordable_func", lambda u: recordable)
    kw.setdefault("extract_key_func", lambda u: (u.chat.id, u.id))
    kw.setdefault("extract_data_func", lambda u: u.text)
    return _BareHistory(**kw)


def _spy(history: UpdateHistory[Any]) -> _SpyStore:
    store = history.store
    assert isinstance(store, _SpyStore)
    return store


# --- class / __init__ ----------------------------------------------------------------------


def test_init_defaults_to_memory_store_bound_to_update_type() -> None:
    history = _BareHistory()
    assert isinstance(history.store, MemoryUpdateHistoryStore)
    assert history.store.update_type is Message
    assert history.is_recordable_func is None
    assert history.extract_key_func is None
    assert history.extract_data_func is None


def test_init_calls_store_factory_with_update_type() -> None:
    seen: list[type] = []

    def factory(update_type: type[Message]) -> _SpyStore:
        seen.append(update_type)
        return _SpyStore(update_type)

    history = _BareHistory(store_factory=factory)
    assert seen == [Message]
    assert isinstance(history.store, _SpyStore)


def test_init_passes_extra_kwargs_along_the_mro() -> None:
    class _Mixin:
        def __init__(self, *, extra: int, **kw: Any) -> None:
            self.extra = extra
            super().__init__(**kw)

    class _MixedHistory(UpdateHistory[Message], _Mixin):
        __update_type__ = Message

    assert _MixedHistory(extra=3).extra == 3


# --- _get_executor -------------------------------------------------------------------------


def test_get_executor_is_none_when_client_has_no_executor() -> None:
    msg = make_message()
    msg._client = SimpleNamespace()
    assert _BareHistory()._get_executor(msg) is None


# --- is_recordable / extract_key / extract_data --------------------------------------------


@pytest.mark.parametrize(
    ("method", "attr"),
    [
        ("is_recordable", "is_recordable_func"),
        ("extract_key", "extract_key_func"),
        ("extract_data", "extract_data_func"),
    ],
)
async def test_hook_without_func_raises_not_implemented(method: str, attr: str) -> None:
    history = _BareHistory()
    with pytest.raises(NotImplementedError, match=rf"_BareHistory must either pass {attr}"):
        await getattr(history, method)(make_message())


@pytest.mark.parametrize("method", ["is_recordable", "extract_key", "extract_data"])
async def test_hook_rejects_wrong_update_type(method: str) -> None:
    history = _history()
    with pytest.raises(TypeError, match="Expected Message, got CallbackQuery"):
        await getattr(history, method)(make_callback_query())


async def test_hooks_run_sync_callables() -> None:
    history = _history(recordable=False)
    msg = make_message(100, 7, 5, text="hi")
    assert await history.is_recordable(msg) is False
    assert await history.extract_key(msg) == (100, 5)
    assert await history.extract_data(msg) == "hi"


async def test_hooks_await_async_callables() -> None:
    async def rec(u: Message) -> bool:
        return True

    async def key(u: Message) -> str:
        return "key"

    async def data(u: Message) -> int:
        return 42

    history = _BareHistory(is_recordable_func=rec, extract_key_func=key, extract_data_func=data)
    msg = make_message()
    assert await history.is_recordable(msg) is True
    assert await history.extract_key(msg) == "key"
    assert await history.extract_data(msg) == 42


async def test_hooks_run_sync_callables_on_the_client_executor() -> None:
    threads: list[str] = []

    def capture(u: Message) -> bool:
        threads.append(threading.current_thread().name)
        return True

    history = _BareHistory(
        is_recordable_func=capture, extract_key_func=capture, extract_data_func=capture
    )
    msg = make_message()
    with ThreadPoolExecutor(max_workers=1, thread_name_prefix="history-exec") as executor:
        msg._client = SimpleNamespace(executor=executor)
        await history.is_recordable(msg)
        await history.extract_key(msg)
        await history.extract_data(msg)

    assert len(threads) == 3
    assert all(name.startswith("history-exec") for name in threads)


# --- record --------------------------------------------------------------------------------


async def test_record_writes_one_record_with_handler_and_data() -> None:
    history = _history()
    await history.record(make_message(100, 7, 5, text="hi"), "H")
    [call] = _spy(history).calls
    assert call[:2] == ("update", (100, 5))
    [record] = call[2]
    assert (record.handler, record.data) == ("H", "hi")


async def test_record_skips_unrecordable_update() -> None:
    history = _history(recordable=False)
    await history.record(make_message(), "H")
    assert _spy(history).calls == []


async def test_record_without_check_does_not_need_is_recordable_func() -> None:
    history = _BareHistory(
        store_factory=_SpyStore, extract_key_func=lambda u: 1, extract_data_func=lambda u: None
    )
    await history.record(make_message(), "H", check=False)
    assert _spy(history).data[1][0].handler == "H"


# --- record_many ---------------------------------------------------------------------------


async def test_record_many_writes_all_handlers_in_one_call_with_one_timestamp() -> None:
    history = _history()
    await history.record_many(make_message(100, 7, 5, text="hi"), ["H1", "H2", "H3"])
    [call] = _spy(history).calls
    assert call[:2] == ("update", (100, 5))
    records = call[2]
    assert [r.handler for r in records] == ["H1", "H2", "H3"]
    assert {r.data for r in records} == {"hi"}
    assert len({r.created_at for r in records}) == 1


async def test_record_many_skips_unrecordable_update() -> None:
    history = _history(recordable=False)
    await history.record_many(make_message(), ["H1", "H2"])
    assert _spy(history).calls == []


async def test_record_many_without_check_skips_is_recordable() -> None:
    history = _history(recordable=False)
    await history.record_many(make_message(), ["H1"], check=False)
    assert [c[0] for c in _spy(history).calls] == ["update"]


async def test_record_many_with_no_handlers_stores_nothing() -> None:
    history = _BareHistory(
        is_recordable_func=lambda u: True,
        extract_key_func=lambda u: "k",
        extract_data_func=lambda u: None,
    )
    await history.record_many(make_message(), [])
    assert await history.get("k") == []


# --- get / pop / clear ---------------------------------------------------------------------


async def test_get_by_update_uses_extracted_key() -> None:
    history = _history()
    msg = make_message(100, 7, 5)
    await history.record(msg, "H")
    assert [r.handler for r in await history.get(msg)] == ["H"]
    assert _spy(history).calls[-1] == ("get", (100, 5))


async def test_get_by_key_skips_is_recordable() -> None:
    history = _history(recordable=False)
    _spy(history).data[(1, 2)] = [UpdateRecord(handler="H")]
    assert [r.handler for r in await history.get((1, 2))] == ["H"]


async def test_get_unrecordable_update_returns_empty_without_store_access() -> None:
    history = _history(recordable=False)
    assert await history.get(make_message()) == []
    assert _spy(history).calls == []


async def test_pop_by_update_removes_and_returns_records() -> None:
    history = _history()
    msg = make_message(100, 7, 5)
    await history.record(msg, "H")
    assert [r.handler for r in await history.pop(msg)] == ["H"]
    assert _spy(history).calls[-1] == ("pop", (100, 5))
    assert await history.get(msg) == []


async def test_pop_by_key_skips_is_recordable() -> None:
    history = _history(recordable=False)
    _spy(history).data["k"] = [UpdateRecord(handler="H")]
    assert [r.handler for r in await history.pop("k")] == ["H"]
    assert "k" not in _spy(history).data


async def test_pop_unrecordable_update_returns_empty_and_removes_nothing() -> None:
    history = _history(recordable=False)
    store = _spy(history)
    store.data[(100, 5)] = [UpdateRecord(handler="H")]
    assert await history.pop(make_message(100, 7, 5)) == []
    assert store.calls == []
    assert (100, 5) in store.data


async def test_clear_by_update_deletes_records() -> None:
    history = _history()
    msg = make_message(100, 7, 5)
    await history.record(msg, "H")
    await history.clear(msg)
    assert _spy(history).calls[-1] == ("delete", (100, 5))
    assert await history.get(msg) == []


async def test_clear_by_key_skips_is_recordable() -> None:
    history = _history(recordable=False)
    _spy(history).data["k"] = [UpdateRecord(handler="H")]
    await history.clear("k")
    assert "k" not in _spy(history).data


async def test_clear_unrecordable_update_deletes_nothing() -> None:
    history = _history(recordable=False)
    store = _spy(history)
    store.data[(100, 5)] = [UpdateRecord(handler="H")]
    await history.clear(make_message(100, 7, 5))
    assert store.calls == []
    assert (100, 5) in store.data


# --- start / stop --------------------------------------------------------------------------


async def test_start_and_stop_delegate_to_the_store() -> None:
    history = _history()
    await history.start()
    await history.stop()
    assert _spy(history).calls == [("start",), ("stop",)]
