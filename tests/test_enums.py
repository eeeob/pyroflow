"""Enum behaviour, including the StrEnum fallback used on Python < 3.11."""

from pyroflow.enums import DuplicatePolicy, UpdateLockState
from pyroflow.utils.enums import TimeUnit


def test_update_lock_state_values():
    assert UpdateLockState.PROCESSING == 0
    assert UpdateLockState.HANDLED == 1
    assert int(UpdateLockState.HANDLED) == 1


def test_duplicate_policy_behaves_like_str_enum():
    # Whether backed by stdlib StrEnum (3.11+) or the local fallback, the
    # members must be real strings with lower-cased auto() values.
    assert isinstance(DuplicatePolicy.REJECT, str)
    assert isinstance(DuplicatePolicy.REPLACE, str)
    assert DuplicatePolicy.REJECT == "reject"
    assert DuplicatePolicy.REPLACE == "replace"


def test_duplicate_policy_membership():
    assert DuplicatePolicy("reject") is DuplicatePolicy.REJECT
    assert DuplicatePolicy("replace") is DuplicatePolicy.REPLACE


def test_time_unit_seconds():
    assert TimeUnit.MINUTE == 60
    assert TimeUnit.HOUR == 60 * 60
    assert TimeUnit.DAY == 60 * 60 * 24
    assert TimeUnit.WEEK == TimeUnit.DAY * 7
