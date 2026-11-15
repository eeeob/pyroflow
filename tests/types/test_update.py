"""Tests for `pyroflow.types.update`: the patched `Update` and its `arrived_at`."""

from __future__ import annotations as _annotations

import pyrogram
from pyrogram.types import CallbackQuery, Message

from pyroflow.types import Update
from pyroflow.types import update as update_module


def test_update_all() -> None:
    assert update_module.__all__ == ("Update",)


def test_update_patches_pyrogram_in_place() -> None:
    assert Update is pyrogram.types.Update


def test_arrived_at_is_none_until_set() -> None:
    assert Message(id=1).arrived_at is None


def test_arrived_at_keeps_the_value_set() -> None:
    message = Message(id=1)

    message.arrived_at = 12.5

    assert message.arrived_at == 12.5


def test_arrived_at_reaches_every_update_type() -> None:
    query = CallbackQuery(client=None, id="1", from_user=None, chat_instance="c")

    query.arrived_at = 3.0

    assert query.arrived_at == 3.0


def test_arrived_at_is_left_out_of_equality_and_repr() -> None:
    message = Message(id=1)

    message.arrived_at = 12.5

    assert message == Message(id=1)
    assert repr(message) == repr(Message(id=1))
    assert str(message) == str(Message(id=1))
