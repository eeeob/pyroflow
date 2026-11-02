"""Runtime checks for the type aliases in pyroflow.typings."""

from __future__ import annotations as _annotations


import pyroflow.typings


def test_typings_all() -> None:
    assert set(pyroflow.typings.__all__) == {
        "UpdateType",
        "AsyncLockProto",
        "UpdateCoordinatorKeyT",
        "UpdateCoordinatorSectionT",
        "UpdateHistoryKeyT",
        "ListenerCoordinatorIdT",
        "LockKeyT",
        "BotCommandEntryT",
        "BotCommandPartsT",
        "BotCommandGroupKeyT",
        "AskErrorHandlersT",
        "ListenMessageIdT",
    }
