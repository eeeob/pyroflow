"""Tests for `pyroflow.types.user`: the patched `User`."""

from __future__ import annotations as _annotations

import pyrogram
import pytest

from pyroflow.types import User
from pyroflow.types import user as user_module


def test_user_all() -> None:
    assert user_module.__all__ == ("User",)


def test_user_patches_pyrogram_in_place() -> None:
    assert User is pyrogram.types.User


# --- User.lang_code -------------------------------------------------------


@pytest.mark.parametrize(
    ("language_code", "expected"),
    [
        ("pt-BR", "pt"),
        ("EN", "en"),
        ("en", "en"),
        ("zh-Hant-TW", "zh"),
        ("", None),
        (None, None),
    ],
)
def test_lang_code(language_code: str | None, expected: str | None) -> None:
    assert User(id=1, language_code=language_code).lang_code == expected
