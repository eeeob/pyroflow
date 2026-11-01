"""Enum behaviour, including the StrEnum fallback used on Python < 3.11."""

from __future__ import annotations as _annotations

import sys
from enum import auto

import pytest

import pyroflow.enums
from pyroflow.enums import DuplicatePolicy


def test_no_update_lock_state() -> None:
    """Coordination has no lock *states* any more: a real mutex holds the
    'in progress' meaning, and the handled registry is a flat set whose
    membership is the whole state. A resurrected enum would signal the
    three-state design creeping back."""
    assert not hasattr(pyroflow.enums, "UpdateLockState")
    assert "UpdateLockState" not in pyroflow.enums.__all__


def test_duplicate_policy_behaves_like_str_enum() -> None:
    # Whether backed by stdlib StrEnum (3.11+) or the local fallback, the
    # members must be real strings with lower-cased auto() values.
    assert isinstance(DuplicatePolicy.REJECT, str)
    assert isinstance(DuplicatePolicy.REPLACE, str)
    assert DuplicatePolicy.REJECT == "reject"
    assert DuplicatePolicy.REPLACE == "replace"


def test_duplicate_policy_membership() -> None:
    assert DuplicatePolicy("reject") is DuplicatePolicy.REJECT
    assert DuplicatePolicy("replace") is DuplicatePolicy.REPLACE


def test_duplicate_policy_str_is_the_value() -> None:
    assert str(DuplicatePolicy.REJECT) == "reject"
    assert str(DuplicatePolicy.REPLACE) == "replace"
    assert f"{DuplicatePolicy.REJECT}" == "reject"


def test_duplicate_policy_members_and_values() -> None:
    assert [m.value for m in DuplicatePolicy] == ["reject", "replace"]
    assert issubclass(DuplicatePolicy, pyroflow.enums.StrEnum)


def test_duplicate_policy_rejects_unknown_value() -> None:
    with pytest.raises(ValueError):
        DuplicatePolicy("REJECT")


def test_enums_all() -> None:
    assert pyroflow.enums.__all__ == ("DuplicatePolicy",)


@pytest.mark.skipif(sys.version_info >= (3, 11), reason="StrEnum backport exists on 3.10 only")
def test_str_enum_backport_generates_lowercase_values() -> None:
    backport = pyroflow.enums.StrEnum
    assert backport._generate_next_value_("Some_Name", 1, 0, []) == "some_name"


@pytest.mark.skipif(sys.version_info >= (3, 11), reason="StrEnum backport exists on 3.10 only")
def test_str_enum_backport_str_returns_value() -> None:
    class Color(pyroflow.enums.StrEnum):
        RED = auto()

    assert Color.RED == "red"
    assert str(Color.RED) == "red"
    assert isinstance(Color.RED, str)
