"""Tests for pyroflow.constants."""

from __future__ import annotations as _annotations

import pyroflow.constants
from pyroflow.constants import ASK_MESSAGE_ID_META_KEY, BOT_COMMANDS_ATTR


def test_bot_commands_attr_is_namespaced() -> None:
    assert BOT_COMMANDS_ATTR == "_pyroflow_bot_commands"
    assert BOT_COMMANDS_ATTR.startswith("_pyroflow")
    assert BOT_COMMANDS_ATTR.isidentifier()


def test_ask_message_id_meta_key_is_the_released_meta_key() -> None:
    # pyroflow 0.2.1 recorded the asked message under this same key.
    assert ASK_MESSAGE_ID_META_KEY == "message_id"


def test_constants_all() -> None:
    assert pyroflow.constants.__all__ == ("ASK_MESSAGE_ID_META_KEY", "BOT_COMMANDS_ATTR")
