"""Tests for `pyroflow.models.ask_again`: AskAgain and AskParser."""

from __future__ import annotations as _annotations

import dataclasses
from typing import Any, get_args

import pytest
from pyrogram.types import Message

from pyroflow.models import AskAgain, AskParser
from pyroflow.models import ask_again as ask_again_module
from pyroflow.typings import QuestionT, ResultT, UpdateType


def test_module_exports() -> None:
    assert ask_again_module.__all__ == ("AskAgain", "AskParser")


def test_ask_again_holds_a_question_and_no_kw_by_default() -> None:
    again = AskAgain("next")

    assert again.question == "next"
    assert again.kw == {}


def test_ask_again_holds_the_kw_given() -> None:
    assert AskAgain("next", {"a": 1}).kw == {"a": 1}


def test_ask_again_is_frozen_and_slotted() -> None:
    again = AskAgain("next")

    assert not hasattr(again, "__dict__")
    with pytest.raises(dataclasses.FrozenInstanceError):
        again.question = "other"  # ty: ignore[invalid-assignment]


def test_ask_parser_is_generic_on_the_update_the_question_and_the_result() -> None:
    assert AskParser.__parameters__ == (UpdateType, QuestionT, ResultT)

    params, result = get_args(AskParser[Message, str, int])

    assert params == [Message, dict[str, Any]]
    assert {AskAgain[str], int} <= set(get_args(result))
