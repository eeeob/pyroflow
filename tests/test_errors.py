"""Tests for pyroflow.errors."""

from __future__ import annotations as _annotations

import pytest

import pyroflow.errors
from pyroflow.errors import (
    CoordinationError,
    ListenerAlreadyExists,
    ListenerCancelled,
    ListenerError,
    ListenerTimeout,
    PyroflowError,
    UpdateAlreadyHandled,
)


def test_pyroflow_error_default_message_and_value() -> None:
    err = PyroflowError()
    assert err.value is None
    assert str(err) == "pyroflow error"
    assert isinstance(err, Exception)


def test_pyroflow_error_falls_back_to_class_name_without_docstring() -> None:
    class NoDoc(PyroflowError):
        pass

    assert NoDoc.__doc__ is None
    assert str(NoDoc(7)) == "NoDoc 7"


def test_pyroflow_error_value_with_braces_is_not_reformatted() -> None:
    assert str(ListenerTimeout("{x}")) == "Listener for {x} timed out"


@pytest.mark.parametrize(
    ("cls", "message"),
    [(ListenerError, "Listener error"), (CoordinationError, "Coordination error")],
)
def test_error_families(cls: type[PyroflowError], message: str) -> None:
    err = cls(5)
    assert isinstance(err, PyroflowError)
    assert str(err) == message
    assert err.value == 5


def test_listener_cancelled_message_and_default_is_duplicate() -> None:
    err = ListenerCancelled("k")
    assert str(err) == "Listener for k was cancelled"
    assert err.value == "k"
    assert err.is_duplicate is False
    assert isinstance(err, ListenerError)


def test_listener_cancelled_is_duplicate() -> None:
    err = ListenerCancelled("k", is_duplicate=True)
    assert err.is_duplicate is True
    assert str(err) == "Listener for k was cancelled"


def test_listener_cancelled_defaults() -> None:
    err = ListenerCancelled()
    assert err.value is None
    assert str(err) == "Listener for None was cancelled"


@pytest.mark.parametrize(
    ("cls", "family", "message"),
    [
        (ListenerTimeout, ListenerError, "Listener for 5 timed out"),
        (ListenerAlreadyExists, ListenerError, "A listener already exists for 5"),
        (UpdateAlreadyHandled, CoordinationError, "Update 5 was already handled"),
    ],
)
def test_error_subclass_messages(
    cls: type[PyroflowError], family: type[PyroflowError], message: str
) -> None:
    err = cls(5)
    assert isinstance(err, family)
    assert str(err) == message
    assert err.value == 5


def test_errors_all() -> None:
    assert pyroflow.errors.__all__ == (
        "PyroflowError",
        "ListenerError",
        "ListenerCancelled",
        "ListenerTimeout",
        "ListenerAlreadyExists",
        "CoordinationError",
        "UpdateAlreadyHandled",
    )
