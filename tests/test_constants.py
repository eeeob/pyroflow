"""Tests for pyroflow.constants."""

from __future__ import annotations as _annotations

import pyroflow.constants
from pyroflow.constants import BOT_COMMANDS_ATTR


def test_bot_commands_attr_is_namespaced() -> None:
    assert BOT_COMMANDS_ATTR == "_pyroflow_bot_commands"
    assert BOT_COMMANDS_ATTR.startswith("_pyroflow")
    assert BOT_COMMANDS_ATTR.isidentifier()


def test_constants_all() -> None:
    assert pyroflow.constants.__all__ == ("BOT_COMMANDS_ATTR",)
