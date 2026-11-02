"""Tests for the ``UpdateCoordinated`` base: the hook contract."""

from __future__ import annotations as _annotations

import logging
import threading
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
from typing import Any

import pytest

from pyrogram.types import Message

from pyroflow.update_coordinated import update_coordinated as module
from pyroflow.update_coordinated.update_coordinated import UpdateCoordinated
from pyroflow.update_coordinator import MemoryUpdateCoordinator

from ..conftest import make_callback_query, make_message


class _Coordinated(UpdateCoordinated[Message]):
    __update_type__ = Message


class _RecordingCoordinator:
    def __init__(self, update_type: type) -> None:
        self.update_type = update_type
        self.calls: list[tuple[str, Any]] = []

    def lock(self, key: Any) -> str:
        self.calls.append(("lock", key))
        return "the-lock"

    async def start(self) -> None:
        self.calls.append(("start", None))

    async def stop(self) -> None:
        self.calls.append(("stop", None))


def test_module_logger_is_named_after_the_module() -> None:
    assert isinstance(module.log, logging.Logger)
    assert module.log.name == "pyroflow.update_coordinated.update_coordinated"


def test_init_defaults_to_memory_coordinator_and_no_callables() -> None:
    policy = _Coordinated()

    assert isinstance(policy.coordinator, MemoryUpdateCoordinator)
    assert policy.coordinator._update_name == "Message"
    assert policy.is_coordinatable_func is None
    assert policy.extract_key_func is None
    assert policy.extract_update_id_func is None


def test_init_builds_coordinator_from_factory_with_update_type() -> None:
    policy = _Coordinated(coordinator_factory=_RecordingCoordinator)

    assert isinstance(policy.coordinator, _RecordingCoordinator)
    assert policy.coordinator.update_type is Message


def test_init_passes_extra_keywords_along_the_mro() -> None:
    class _Mixin:
        def __init__(self, extra: str = "", **kw: Any) -> None:
            self.extra = extra
            super().__init__(**kw)

    class _Mixed(UpdateCoordinated[Message], _Mixin):
        __update_type__ = Message

    assert _Mixed(extra="seen").extra == "seen"


@pytest.mark.parametrize(
    ("method", "attribute"),
    [
        ("is_coordinatable", "is_coordinatable_func"),
        ("extract_key", "extract_key_func"),
        ("extract_update_id", "extract_update_id_func"),
    ],
)
async def test_hook_without_callable_names_class_and_hook(method: str, attribute: str) -> None:
    with pytest.raises(NotImplementedError) as exc_info:
        await getattr(_Coordinated(), method)(make_message())

    assert str(exc_info.value) == (
        f"_Coordinated must either pass {attribute} or override {method}()"
    )


@pytest.mark.parametrize(
    ("method", "attribute"),
    [
        ("is_coordinatable", "is_coordinatable_func"),
        ("extract_key", "extract_key_func"),
        ("extract_update_id", "extract_update_id_func"),
    ],
)
async def test_hook_rejects_wrong_update_type(method: str, attribute: str) -> None:
    calls: list[object] = []
    policy = _Coordinated(**{attribute: calls.append})

    with pytest.raises(TypeError, match="Expected Message, got CallbackQuery"):
        await getattr(policy, method)(make_callback_query())

    assert calls == []


@pytest.mark.parametrize(
    ("method", "attribute"),
    [
        ("is_coordinatable", "is_coordinatable_func"),
        ("extract_key", "extract_key_func"),
        ("extract_update_id", "extract_update_id_func"),
    ],
)
async def test_hook_returns_sync_callable_result(method: str, attribute: str) -> None:
    message = make_message(message_id=9)
    policy = _Coordinated(**{attribute: lambda u: ("sync", u.id)})

    assert await getattr(policy, method)(message) == ("sync", 9)


@pytest.mark.parametrize(
    ("method", "attribute"),
    [
        ("is_coordinatable", "is_coordinatable_func"),
        ("extract_key", "extract_key_func"),
        ("extract_update_id", "extract_update_id_func"),
    ],
)
async def test_hook_awaits_async_callable(method: str, attribute: str) -> None:
    async def func(u: Message) -> tuple[str, int]:
        return ("async", u.id)

    policy = _Coordinated(**{attribute: func})

    assert await getattr(policy, method)(make_message(message_id=3)) == ("async", 3)


@pytest.mark.parametrize(
    ("method", "attribute"),
    [
        ("is_coordinatable", "is_coordinatable_func"),
        ("extract_key", "extract_key_func"),
        ("extract_update_id", "extract_update_id_func"),
    ],
)
async def test_hook_runs_sync_callable_on_client_executor(method: str, attribute: str) -> None:
    executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="client-executor")
    try:
        message = make_message()
        message._client = SimpleNamespace(executor=executor)
        policy = _Coordinated(**{attribute: lambda u: threading.current_thread().name})

        assert (await getattr(policy, method)(message)).startswith("client-executor")
    finally:
        executor.shutdown()


async def test_lock_asks_coordinator_for_the_extracted_key() -> None:
    policy = _Coordinated(
        coordinator_factory=_RecordingCoordinator,
        extract_key_func=lambda u: ("scope", u.id),
    )

    assert await policy.lock(make_message(message_id=4)) == "the-lock"
    assert policy.coordinator.calls == [("lock", ("scope", 4))]


async def test_lock_returns_an_unacquired_memory_lock() -> None:
    policy = _Coordinated(extract_key_func=lambda u: (u.id,))
    message = make_message()

    lock = await policy.lock(message)

    assert not lock.locked()
    assert await lock.acquire() is True
    await lock.release()


async def test_start_and_stop_delegate_to_coordinator() -> None:
    policy = _Coordinated(coordinator_factory=_RecordingCoordinator)

    await policy.start()
    await policy.stop()

    assert policy.coordinator.calls == [("start", None), ("stop", None)]


def test_module_exports_only_the_base() -> None:
    assert module.__all__ == ("UpdateCoordinated",)
