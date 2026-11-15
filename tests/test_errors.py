"""Tests for `pyroflow.errors`."""

from __future__ import annotations as _annotations

import copy
import pickle
from typing import TYPE_CHECKING

import pytest

import pyroflow.errors
from pyroflow.errors import (
    ListenerAlreadyExists,
    ListenerAttemptsExhausted,
    ListenerCancelled,
    ListenerClosed,
    ListenerError,
    ListenerEvicted,
    ListenerNotSent,
    ListenerRejected,
    ListenerReplaced,
    ListenerTimeout,
    ListenerWorkersBusy,
    PyroflowError,
)

if TYPE_CHECKING:
    from collections.abc import Callable


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


def test_listener_error_family() -> None:
    err = ListenerError(5)
    assert isinstance(err, PyroflowError)
    assert str(err) == "Listener error"
    assert err.value == 5


def test_listener_cancelled_message() -> None:
    err = ListenerCancelled("k")
    assert str(err) == "Listener for k was cancelled"
    assert err.value == "k"
    assert isinstance(err, ListenerError)


def test_listener_rejected_message_and_family() -> None:
    err = ListenerRejected("k")
    assert str(err) == "Listener for k was rejected by its filters"
    assert err.value == "k"
    assert isinstance(err, ListenerCancelled)


def test_listener_closed_message_needs_no_key() -> None:
    err = ListenerClosed()
    assert str(err) == "The listener is closed: it was stopped and not started again"
    assert err.value is None
    assert isinstance(err, ListenerCancelled)


@pytest.mark.parametrize(
    "err",
    [ListenerTimeout(5), ListenerClosed(), ListenerAttemptsExhausted(3, "update")],
)
# The pickle round trip only loads what the test itself just dumped.
@pytest.mark.parametrize("duplicate", [copy.copy, lambda err: pickle.loads(pickle.dumps(err))])
def test_pyroflow_error_reduce_keeps_the_message_and_attributes(
    err: PyroflowError, duplicate: Callable[[PyroflowError], PyroflowError]
) -> None:
    copied = duplicate(err)
    assert type(copied) is type(err)
    assert str(copied) == str(err)
    assert vars(copied) == vars(err)


def test_listener_cancelled_defaults() -> None:
    err = ListenerCancelled()
    assert err.value is None
    assert str(err) == "Listener for None was cancelled"


@pytest.mark.parametrize(
    ("cls", "family", "message"),
    [
        (ListenerTimeout, ListenerError, "Listener for 5 timed out"),
        (ListenerAlreadyExists, ListenerError, "A listener already exists for 5"),
        (
            ListenerReplaced,
            ListenerCancelled,
            "Listener for 5 was replaced by a newer one on the same key",
        ),
        (ListenerWorkersBusy, ListenerError, "No free worker for a wait on 5"),
        (
            ListenerEvicted,
            ListenerCancelled,
            "Listener for 5 was cancelled to free the worker its handler held",
        ),
    ],
)
def test_error_subclass_messages(
    cls: type[PyroflowError], family: type[PyroflowError], message: str
) -> None:
    err = cls(5)
    assert isinstance(err, family)
    assert str(err) == message
    assert err.value == 5


def test_listener_attempts_exhausted_keeps_the_value_and_the_update() -> None:
    update = object()
    err = ListenerAttemptsExhausted(3, update)
    assert isinstance(err, ListenerError)
    assert str(err) == "No attempts left out of 3"
    assert err.value == 3
    assert err.update is update


def test_listener_attempts_exhausted_defaults() -> None:
    err = ListenerAttemptsExhausted()
    assert err.value is None
    assert err.update is None
    assert str(err) == "No attempts left out of None"


def test_listener_not_sent_message_and_family() -> None:
    err = ListenerNotSent()
    assert str(err) == (
        "Telegram returned no message for the question, so there is nothing to wait on"
    )
    assert err.value is None
    assert isinstance(err, ListenerError)


def test_errors_all() -> None:
    assert pyroflow.errors.__all__ == (
        "PyroflowError",
        "ListenerError",
        "ListenerCancelled",
        "ListenerReplaced",
        "ListenerClosed",
        "ListenerRejected",
        "ListenerTimeout",
        "ListenerEvicted",
        "ListenerWorkersBusy",
        "ListenerAlreadyExists",
        "ListenerNotSent",
        "ListenerAttemptsExhausted",
    )
