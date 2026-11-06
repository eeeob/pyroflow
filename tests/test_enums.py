"""Enum behaviour, including the StrEnum fallback used on Python < 3.11."""

from __future__ import annotations as _annotations

import sys
from enum import auto

import pytest

import pyroflow.enums
from pyroflow.enums import (
    DuplicatePolicy,
    EphemeralUpdates,
    ListenMessageId,
    MessageListenCancelPolicy,
    WorkersBusyMode,
    ListenerScope,
)


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


def test_message_listen_cancel_policy_values() -> None:
    assert [str(policy) for policy in MessageListenCancelPolicy] == [
        "always",
        "unresolved",
        "resolved",
    ]


def test_listener_scope_values() -> None:
    assert [str(scope) for scope in ListenerScope] == ["all", "first"]


def test_listen_message_id_values() -> None:
    assert [str(value) for value in ListenMessageId] == ["auto", "sent", "next"]


def test_ephemeral_updates_values() -> None:
    assert [str(value) for value in EphemeralUpdates] == ["any"]


def test_workers_busy_mode_values() -> None:
    assert [str(mode) for mode in WorkersBusyMode] == ["reject", "cancel_oldest"]


def test_enums_all() -> None:
    assert pyroflow.enums.__all__ == (
        "DuplicatePolicy",
        "MessageListenCancelPolicy",
        "ListenerScope",
        "ListenMessageId",
        "EphemeralUpdates",
        "WorkersBusyMode",
    )


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
