"""Tests for `pyroflow.utils.helpers`: `UpdateBound`, `get_update_executor`, and `call_maybe_async`."""

from __future__ import annotations as _annotations

import functools
import threading
from abc import ABC
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
from typing import Any

import pytest

from pyroflow.utils import (
    UpdateBound,
    call_maybe_async,
    get_update_executor,
    helpers,
)
from pyrogram.types import Message


# --- UpdateBound ----------------------------------------------------------


def test_update_bound_rejects_non_update_type() -> None:
    with pytest.raises(TypeError):

        class BadType(UpdateBound):  # pragma: no cover - class body raises
            __update_type__ = int


# --- _check_update_type ----------------------------------------------------


def test_check_update_type_accepts_a_pyrogram_update_class() -> None:
    assert helpers._check_update_type(type("Good", (), {"__update_type__": Message})) is None


@pytest.mark.parametrize(
    ("update_type", "message"),
    [
        (None, "Bad must define __update_type__"),
        (int, "Bad.__update_type__ must be a subclass of Update"),
        (Message(id=1), "Bad.__update_type__ must be a subclass of Update"),
    ],
)
def test_check_update_type_rejects_a_missing_or_wrong_type(
    update_type: object, message: str
) -> None:
    with pytest.raises(TypeError, match=message):
        helpers._check_update_type(type("Bad", (), {"__update_type__": update_type}))


# --- UpdateBound: more branches ------------------------------------------


def test_update_bound_missing_type_message() -> None:
    with pytest.raises(TypeError, match="Missing must define __update_type__"):

        class Missing(UpdateBound):  # pragma: no cover - class body raises
            pass


def test_update_bound_rejects_an_update_instance() -> None:
    with pytest.raises(TypeError, match=r"__update_type__ must be a subclass of Update"):

        class Instance(UpdateBound):  # pragma: no cover - class body raises
            __update_type__ = Message(id=1)


def test_update_bound_abc_exemption_needs_abc_as_a_direct_base() -> None:
    class Abstract(ABC, UpdateBound):
        pass

    with pytest.raises(TypeError, match="must define __update_type__"):

        class Concrete(Abstract):  # pragma: no cover - class body raises
            pass


def test_update_bound_subclass_inherits_update_type() -> None:
    class Good(UpdateBound):
        __update_type__ = Message

    class Child(Good):
        pass

    assert Child.__update_type__ is Message


def test_update_bound_init_subclass_forwards_kwargs() -> None:
    seen: dict[str, Any] = {}

    class Recorder:
        def __init_subclass__(cls, **kw: Any) -> None:
            seen.update(kw)
            super().__init_subclass__()

    class Good(UpdateBound, Recorder, flag=True):
        __update_type__ = Message

    assert seen == {"flag": True}


def test_update_bound_init_passes_kwargs_to_the_next_base() -> None:
    class Store:
        def __init__(self, **kw: Any) -> None:
            self.kw = kw

    class Good(UpdateBound, Store):
        __update_type__ = Message

    assert Good(a=1).kw == {"a": 1}


def test_update_bound_init_rejects_an_abstract_subclass_without_type() -> None:
    class Abstract(ABC, UpdateBound):
        pass

    with pytest.raises(TypeError, match="Abstract must define __update_type__"):
        Abstract()


def test_update_bound_init_rejects_a_type_replaced_after_definition() -> None:
    class Good(UpdateBound):
        __update_type__ = Message

    Good.__update_type__ = int  # type: ignore[assignment]

    with pytest.raises(TypeError, match=r"Good.__update_type__ must be a subclass of Update"):
        Good()


def test_validate_update_accepts_a_subclass_instance() -> None:
    class SubMessage(Message):
        pass

    class Good(UpdateBound):
        __update_type__ = Message

    Good.validate_update(SubMessage(id=1))


def test_validate_update_error_message() -> None:
    class Good(UpdateBound):
        __update_type__ = Message

    with pytest.raises(TypeError, match="Expected Message, got str"):
        Good.validate_update("text")


# --- get_update_executor ----------------------------------------------------


def test_get_update_executor_returns_the_client_executor() -> None:
    executor = ThreadPoolExecutor(max_workers=1)
    try:
        update = SimpleNamespace(_client=SimpleNamespace(executor=executor))
        assert get_update_executor(update) is executor
    finally:
        executor.shutdown()


def test_get_update_executor_without_client() -> None:
    assert get_update_executor(SimpleNamespace()) is None


def test_get_update_executor_client_without_executor() -> None:
    assert get_update_executor(SimpleNamespace(_client=SimpleNamespace())) is None


# --- call_maybe_async -----------------------------------------------------------


async def test_call_maybe_async_awaits_a_coroutine_function() -> None:
    async def add(a: int, b: int) -> int:
        return a + b

    assert await call_maybe_async(add, 1, 2) == 3


async def test_call_maybe_async_awaits_a_partial_around_a_coroutine_function() -> None:
    async def add(a: int, b: int) -> int:
        return a + b

    assert await call_maybe_async(functools.partial(add, 1), 2) == 3


async def test_call_maybe_async_runs_a_sync_callable_on_the_executor() -> None:
    executor = ThreadPoolExecutor(1, thread_name_prefix="pyroflow-call")
    try:
        name = await call_maybe_async(lambda: threading.current_thread().name, executor=executor)
    finally:
        executor.shutdown()

    assert name.startswith("pyroflow-call")


async def test_call_maybe_async_raises_what_the_callable_raises() -> None:
    async def fail() -> None:
        msg = "boom"
        raise ValueError(msg)

    def fail_sync() -> None:
        msg = "sync"
        raise KeyError(msg)

    with pytest.raises(ValueError, match="boom"):
        await call_maybe_async(fail)

    with pytest.raises(KeyError, match="sync"):
        await call_maybe_async(fail_sync)


def test_handler_worker_var_is_unset_outside_a_worker() -> None:
    assert helpers.handler_worker_var.get() is None


def test_module_all_lists_public_names() -> None:
    assert helpers.__all__ == (
        "handler_worker_var",
        "UpdateBound",
        "get_update_executor",
        "call_maybe_async",
    )
