"""Runtime checks for the type aliases in pyroflow.typings."""

from __future__ import annotations as _annotations

import inspect
from collections.abc import Callable
from typing import get_args, get_origin

import pytest
from pyrogram.types import BotCommand, BotCommandScope, Update as PyroUpdate

import pyroflow.typings
from pyroflow.models import ListenerKey
from pyroflow.typings import (
    AskErrorHandlersT,
    AsyncLockProto,
    BotCommandEntryT,
    BotCommandGroupKeyT,
    BotCommandPartsT,
    ListenMessageIdT,
    ListenerCoordinatorIdT,
    LockKeyT,
    UpdateCoordinatorKeyT,
    UpdateCoordinatorSectionT,
    UpdateHistoryKeyT,
    UpdateType,
)


def test_update_type_is_bound_to_pyrogram_update() -> None:
    assert UpdateType.__bound__ is PyroUpdate


def test_update_coordinator_key_is_a_variadic_tuple() -> None:
    assert get_origin(UpdateCoordinatorKeyT) is tuple
    assert get_args(UpdateCoordinatorKeyT) == (int | str, ...)
    assert UpdateHistoryKeyT is UpdateCoordinatorKeyT


def test_listener_coordinator_id_is_str_or_int() -> None:
    assert set(get_args(ListenerCoordinatorIdT)) == {str, int}


def test_lock_key_accepts_int_tuples_and_listener_key() -> None:
    args = get_args(LockKeyT)
    assert int in args
    assert ListenerKey in args
    assert tuple[int] in args
    assert tuple[int, int | None] in args
    assert tuple[int, int | None, int | None] in args


def test_update_coordinator_section_literal() -> None:
    assert get_args(UpdateCoordinatorSectionT) == ("lock", "handled")


def test_bot_command_entry_shapes() -> None:
    tuples = [a for a in get_args(BotCommandEntryT) if get_origin(a) is tuple]
    assert sorted(len(get_args(t)) for t in tuples) == [2, 3]
    assert BotCommand in get_args(get_args(BotCommandEntryT)[0])


def test_bot_command_parts_and_group_key() -> None:
    assert get_origin(BotCommandPartsT) is tuple
    assert len(get_args(BotCommandPartsT)) == 3
    assert get_args(BotCommandGroupKeyT) == (str | None, BotCommandScope | None)


def test_ask_error_handlers_is_a_dict_of_exception_types() -> None:
    assert get_origin(AskErrorHandlersT) is dict
    key, _value = get_args(AskErrorHandlersT)
    assert type[Exception] in get_args(key)


def test_listen_message_id_is_int_or_callable() -> None:
    int_arg, callable_arg = get_args(ListenMessageIdT)
    assert int_arg is int
    assert get_origin(callable_arg) is Callable
    params, ret = get_args(callable_arg)
    # The forward reference is a str or a ForwardRef depending on the Python version.
    assert len(params) == 1
    assert "Message" in str(params[0])
    assert ret == int | None


def test_async_lock_proto_is_not_runtime_checkable() -> None:
    with pytest.raises(TypeError):
        isinstance(object(), AsyncLockProto)


def test_async_lock_proto_methods_are_coroutines() -> None:
    for name in ("acquire", "release", "__aenter__", "__aexit__"):
        assert inspect.iscoroutinefunction(getattr(AsyncLockProto, name)), name
    params = list(inspect.signature(AsyncLockProto.__aexit__).parameters.values())[1:]
    assert [p.kind for p in params] == [inspect.Parameter.POSITIONAL_ONLY] * 3


async def test_async_lock_proto_stub_bodies_return_none() -> None:
    assert await AsyncLockProto.acquire(None) is None  # type: ignore[arg-type]
    assert await AsyncLockProto.release(None) is None  # type: ignore[arg-type]
    assert await AsyncLockProto.__aenter__(None) is None  # type: ignore[arg-type]
    assert await AsyncLockProto.__aexit__(None, None, None, None) is None  # type: ignore[arg-type]


async def test_async_lock_proto_structural_fake_works_in_async_with() -> None:
    events: list[str] = []

    class FakeLock:
        async def acquire(self) -> bool:
            events.append("acquire")
            return True

        async def release(self) -> None:
            events.append("release")

        async def __aenter__(self) -> object:
            await self.acquire()
            return self

        async def __aexit__(self, exc_type: object, exc: object, tb: object, /) -> None:
            await self.release()

    lock: AsyncLockProto = FakeLock()
    async with lock:
        events.append("body")
    assert events == ["acquire", "body", "release"]


def test_typings_all() -> None:
    assert len(pyroflow.typings.__all__) == 12
    assert set(pyroflow.typings.__all__) == {
        "UpdateType",
        "AsyncLockProto",
        "UpdateCoordinatorKeyT",
        "UpdateCoordinatorSectionT",
        "UpdateHistoryKeyT",
        "ListenerCoordinatorIdT",
        "LockKeyT",
        "BotCommandEntryT",
        "BotCommandPartsT",
        "BotCommandGroupKeyT",
        "AskErrorHandlersT",
        "ListenMessageIdT",
    }
