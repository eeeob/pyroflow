"""Tests for pyroflow.errors."""

from __future__ import annotations as _annotations

import pytest

import pyroflow.errors
from pyroflow.errors import (
    ListenerAlreadyExists,
    ListenerCancelled,
    ListenerError,
    ListenerTimeout,
    UnhandledUpdate,
    UnresolvedUpdate,
)


def test_listener_error_default_message_and_value() -> None:
    err = ListenerError()
    assert err.value is None
    assert str(err) == "Listener error"
    assert isinstance(err, Exception)


def test_listener_error_stores_value() -> None:
    value = object()
    assert ListenerError(value).value is value


def test_listener_error_falls_back_to_class_name_without_docstring() -> None:
    class NoDoc(ListenerError):
        pass

    assert NoDoc.__doc__ is None
    assert str(NoDoc(7)) == "NoDoc 7"


def test_listener_error_value_with_braces_is_not_reformatted() -> None:
    assert str(ListenerTimeout("{x}")) == "UpdateListener {x} timed out"


def test_listener_cancelled_message_and_default_is_duplicate() -> None:
    err = ListenerCancelled("k")
    assert str(err) == "UpdateListener k was cancelled"
    assert err.value == "k"
    assert err.is_duplicate is False
    assert isinstance(err, ListenerError)


def test_listener_cancelled_is_duplicate() -> None:
    err = ListenerCancelled("k", is_duplicate=True)
    assert err.is_duplicate is True
    assert str(err) == "UpdateListener k was cancelled"


def test_listener_cancelled_defaults() -> None:
    err = ListenerCancelled()
    assert err.value is None
    assert str(err) == "UpdateListener None was cancelled"


@pytest.mark.parametrize(
    ("cls", "message"),
    [
        (ListenerTimeout, "UpdateListener 5 timed out"),
        (ListenerAlreadyExists, "UpdateListener already exists for key 5"),
        (UnresolvedUpdate, "UnresolvedUpdate 5"),
        (UnhandledUpdate, "UnhandledUpdate 5"),
    ],
)
def test_listener_error_subclass_messages(cls: type[ListenerError], message: str) -> None:
    err = cls(5)
    assert str(err) == message
    assert err.value == 5
    assert isinstance(err, ListenerError)
    with pytest.raises(ListenerError):
        raise err


def test_errors_all() -> None:
    assert pyroflow.errors.__all__ == (
        "ListenerError",
        "ListenerCancelled",
        "ListenerTimeout",
        "ListenerAlreadyExists",
        "UnresolvedUpdate",
        "UnhandledUpdate",
    )
