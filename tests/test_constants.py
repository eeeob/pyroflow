"""Tests for pyroflow.constants."""

from __future__ import annotations as _annotations

import pyroflow.constants


def test_constants_all() -> None:
    assert pyroflow.constants.__all__ == ("BOT_COMMANDS_ATTR",)
