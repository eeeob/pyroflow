"""Runtime checks for the type aliases in pyroflow.typings."""

from __future__ import annotations as _annotations

from collections.abc import Hashable

from typing import ForwardRef, get_args, get_origin

from pyrogram.types import BotCommand, BotCommandScope, Update as PyroUpdate

import pyroflow.typings
from pyroflow.typings import (
    BotCommandEntryT,
    BotCommandGroupKeyT,
    BotCommandPartsT,
    KeyT,
    UpdateType,
)


def test_update_type_is_bound_to_pyrogram_update() -> None:
    assert UpdateType.__bound__ is PyroUpdate


def test_key_type_is_bound_to_listener_key() -> None:
    assert isinstance(KeyT.__bound__, ForwardRef)
    assert KeyT.__bound__.__forward_arg__ == "ListenerKey"


def test_bot_command_entry_shapes() -> None:
    tuples = [a for a in get_args(BotCommandEntryT) if get_origin(a) is tuple]
    assert sorted(len(get_args(t)) for t in tuples) == [2, 3]
    assert BotCommand in get_args(get_args(BotCommandEntryT)[0])


def test_bot_command_parts_and_group_key() -> None:
    assert get_origin(BotCommandPartsT) is tuple
    assert len(get_args(BotCommandPartsT)) == 3
    assert get_args(BotCommandGroupKeyT) == (str | None, BotCommandScope | None)


def test_coordination_key_is_any_hashable_value() -> None:
    assert pyroflow.typings.CoordinationKeyT is Hashable


def test_typings_all() -> None:
    assert set(pyroflow.typings.__all__) == {
        "UpdateType",
        "KeyT",
        "BotCommandEntryT",
        "BotCommandPartsT",
        "BotCommandGroupKeyT",
        "CoordinationKeyT",
    }
