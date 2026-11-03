"""Tests for the generic ``UpdateHistory`` policy: its store and injected extractors."""

from __future__ import annotations as _annotations

import threading
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
from typing import Any, TYPE_CHECKING

import pytest

from pyrogram.types import Message

from pyroflow.update_history import update_history
from pyroflow.update_history.update_history import UpdateHistory
from pyroflow.update_history_store.memory_update_history_store import (
    MemoryUpdateHistoryStore,
)
from pyroflow.update_history_store.update_history_store import UpdateHistoryStore

from ..conftest import make_callback_query, make_message

if TYPE_CHECKING:
    from pyroflow.models import UpdateRecord


# --- helpers -------------------------------------------------------------------------------


class _SpyStore(UpdateHistoryStore):
    """A store that logs its lifecycle calls."""

    def __init__(self, update_type: type[Message], **kw: Any) -> None:
        super().__init__(update_type, **kw)
        self.calls: list[str] = []

    async def update(self, key: Any, *records: UpdateRecord) -> None:
        raise NotImplementedError

    async def get(self, key: Any) -> list[UpdateRecord]:
        raise NotImplementedError

    async def pop(self, key: Any) -> list[UpdateRecord]:
        raise NotImplementedError

    async def delete(self, key: Any) -> None:
        raise NotImplementedError

    async def start(self) -> None:
        self.calls.append("start")

    async def stop(self) -> None:
        self.calls.append("stop")


class _BareHistory(UpdateHistory[Message]):
    __update_type__ = Message


def _history(**kw: Any) -> _BareHistory:
    kw.setdefault("extract_key_func", lambda u: (u.chat.id, u.id))
    kw.setdefault("extract_data_func", lambda u: u.text)
    return _BareHistory(**kw)


# --- class / __init__ ----------------------------------------------------------------------


def test_init_defaults_to_memory_store_bound_to_update_type() -> None:
    history = _BareHistory()
    assert isinstance(history.store, MemoryUpdateHistoryStore)
    assert history.store.update_type is Message
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


# --- extract_key / extract_data ------------------------------------------------------------


@pytest.mark.parametrize(
    ("method", "attr"),
    [("extract_key", "extract_key_func"), ("extract_data", "extract_data_func")],
)
async def test_hook_without_func_raises_not_implemented(method: str, attr: str) -> None:
    history = _BareHistory()
    with pytest.raises(NotImplementedError, match=rf"_BareHistory must either pass {attr}"):
        await getattr(history, method)(make_message())


@pytest.mark.parametrize("method", ["extract_key", "extract_data"])
async def test_hook_rejects_wrong_update_type(method: str) -> None:
    with pytest.raises(TypeError, match="Expected Message, got CallbackQuery"):
        await getattr(_history(), method)(make_callback_query())


async def test_hooks_run_sync_callables() -> None:
    msg = make_message(100, 7, 5, text="hi")
    history = _history()
    assert await history.extract_key(msg) == (100, 5)
    assert await history.extract_data(msg) == "hi"


async def test_hooks_await_async_callables() -> None:
    async def key(u: Message) -> tuple[str]:
        return ("key",)

    async def data(u: Message) -> int:
        return 42

    history = _BareHistory(extract_key_func=key, extract_data_func=data)
    msg = make_message()
    assert await history.extract_key(msg) == ("key",)
    assert await history.extract_data(msg) == 42


async def test_extract_key_passes_none_through() -> None:
    assert await _history(extract_key_func=lambda u: None).extract_key(make_message()) is None


async def test_hooks_run_sync_callables_on_the_client_executor() -> None:
    threads: list[str] = []

    def capture(u: Message) -> tuple[int]:
        threads.append(threading.current_thread().name)
        return (1,)

    history = _BareHistory(extract_key_func=capture, extract_data_func=capture)
    msg = make_message()
    with ThreadPoolExecutor(max_workers=1, thread_name_prefix="history-exec") as executor:
        msg._client = SimpleNamespace(executor=executor)
        await history.extract_key(msg)
        await history.extract_data(msg)

    assert len(threads) == 2
    assert all(name.startswith("history-exec") for name in threads)


# --- start / stop --------------------------------------------------------------------------


async def test_start_and_stop_delegate_to_the_store() -> None:
    history = _history(store_factory=_SpyStore)
    await history.start()
    await history.stop()

    store = history.store
    assert isinstance(store, _SpyStore)
    assert store.calls == ["start", "stop"]


def test_module_all_lists_public_names() -> None:
    assert update_history.__all__ == ("UpdateHistory",)
