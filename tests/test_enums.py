"""Enum behaviour, including the StrEnum fallback used on Python < 3.11."""

import pyroflow.enums
from pyroflow.enums import DuplicatePolicy
from pyroflow.utils.enums import TimeUnit


def test_no_update_lock_state():
    """Coordination has no lock *states* any more: a real mutex holds the
    'in progress' meaning, and the handled registry is a flat set whose
    membership is the whole state. A resurrected enum would signal the
    three-state design creeping back."""
    assert not hasattr(pyroflow.enums, "UpdateLockState")
    assert "UpdateLockState" not in pyroflow.enums.__all__


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
