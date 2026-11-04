"""Runtime checks for the type aliases in pyroflow.typings."""

from __future__ import annotations as _annotations

from collections.abc import Callable, Hashable
from typing import get_args, get_origin

from pyrogram.types import BotCommand, BotCommandScope, Update as PyroUpdate

import pyroflow.typings
from pyroflow.typings import (
    BotCommandEntryT,
    BotCommandGroupKeyT,
    BotCommandPartsT,
    ListenMessageIdT,
    MetaT,
    UpdateType,
)


def test_update_type_is_bound_to_pyrogram_update() -> None:
    assert UpdateType.__bound__ is PyroUpdate


def test_bot_command_entry_shapes() -> None:
    tuples = [a for a in get_args(BotCommandEntryT) if get_origin(a) is tuple]
    assert sorted(len(get_args(t)) for t in tuples) == [2, 3]
    assert BotCommand in get_args(get_args(BotCommandEntryT)[0])


def test_bot_command_parts_and_group_key() -> None:
    assert get_origin(BotCommandPartsT) is tuple
    assert len(get_args(BotCommandPartsT)) == 3
    assert get_args(BotCommandGroupKeyT) == (str | None, BotCommandScope | None)


def test_listen_message_id_is_int_or_callable() -> None:
    int_arg, callable_arg = get_args(ListenMessageIdT)
    assert int_arg is int
    assert get_origin(callable_arg) is Callable
    params, ret = get_args(callable_arg)
    # The forward reference is a str or a ForwardRef depending on the Python version.
    assert len(params) == 1
    assert "Message" in str(params[0])
    assert ret == int | None


def test_meta_is_a_dict_with_hashable_keys() -> None:
    assert get_origin(MetaT) is dict
    assert get_args(MetaT)[0] is Hashable


def test_typings_all() -> None:
    assert set(pyroflow.typings.__all__) == {
        "UpdateType",
        "BotCommandEntryT",
        "BotCommandPartsT",
        "BotCommandGroupKeyT",
        "ListenMessageIdT",
        "MetaT",
    }
