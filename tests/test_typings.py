"""Runtime checks for the type aliases in pyroflow.typings."""

from __future__ import annotations as _annotations

from collections.abc import Callable
from typing import get_args, get_origin

import pytest

from pyrogram.types import BotCommand, BotCommandScope, Update as PyroUpdate

import pyroflow.typings
from pyroflow.typings import (
    AskErrorHandlersT,
    AsyncLockProto,
    BotCommandEntryT,
    BotCommandGroupKeyT,
    BotCommandPartsT,
    ListenMessageIdT,
    ListenerCoordinatorIdT,
    CoordinatedUpdateIdT,
    CoordinatedUpdateKeyT,
    UpdateHistoryKeyT,
    UpdateType,
)


def test_update_type_is_bound_to_pyrogram_update() -> None:
    assert UpdateType.__bound__ is PyroUpdate


@pytest.mark.parametrize("alias", [CoordinatedUpdateKeyT, CoordinatedUpdateIdT, UpdateHistoryKeyT])
def test_key_and_id_aliases_are_variadic_tuples_of_ids(alias: object) -> None:
    assert get_origin(alias) is tuple
    assert get_args(alias) == (int | str, ...)


def test_listener_coordinator_id_is_str_or_int() -> None:
    assert set(get_args(ListenerCoordinatorIdT)) == {str, int}


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


async def test_async_lock_proto_stub_bodies_return_none() -> None:
    assert await AsyncLockProto.acquire(None) is None  # type: ignore[arg-type]
    assert await AsyncLockProto.release(None) is None  # type: ignore[arg-type]
    assert await AsyncLockProto.__aenter__(None) is None  # type: ignore[arg-type]
    assert await AsyncLockProto.__aexit__(None, None, None, None) is None  # type: ignore[arg-type]


def test_typings_all() -> None:
    assert set(pyroflow.typings.__all__) == {
        "UpdateType",
        "AsyncLockProto",
        "CoordinatedUpdateKeyT",
        "CoordinatedUpdateIdT",
        "UpdateHistoryKeyT",
        "ListenerCoordinatorIdT",
        "BotCommandEntryT",
        "BotCommandPartsT",
        "BotCommandGroupKeyT",
        "AskErrorHandlersT",
        "ListenMessageIdT",
    }
