"""Enum behaviour, including the StrEnum fallback used on Python < 3.11."""

from __future__ import annotations as _annotations


import pyroflow.enums
from pyroflow.enums import DuplicatePolicy


def test_duplicate_policy_behaves_like_str_enum() -> None:
    # Whether backed by stdlib StrEnum (3.11+) or the local fallback, the
    # members must be real strings with lower-cased auto() values.
    assert isinstance(DuplicatePolicy.REJECT, str)
    assert isinstance(DuplicatePolicy.REPLACE, str)
    assert DuplicatePolicy.REJECT == "reject"
    assert DuplicatePolicy.REPLACE == "replace"


def test_duplicate_policy_str_is_the_value() -> None:
    assert str(DuplicatePolicy.REJECT) == "reject"
    assert str(DuplicatePolicy.REPLACE) == "replace"
    assert f"{DuplicatePolicy.REJECT}" == "reject"


def test_enums_all() -> None:
    assert pyroflow.enums.__all__ == ("DuplicatePolicy",)
