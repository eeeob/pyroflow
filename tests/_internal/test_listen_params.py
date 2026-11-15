"""Tests for `pyroflow._internal.listen_params`."""

from __future__ import annotations as _annotations

import pyroflow
from pyroflow._internal import listen_params as module
from pyroflow._internal.listen_params import ListenKw


def test_module_all() -> None:
    assert module.__all__ == ("ListenKw",)


def test_listen_kw_holds_the_optional_arguments_of_a_wait() -> None:
    assert ListenKw.__required_keys__ == frozenset()
    assert list(ListenKw.__annotations__) == ["context", "filters", "strict", "timeout"]


def test_listen_kw_stays_out_of_the_public_names() -> None:
    assert not hasattr(pyroflow, "ListenKw")
    assert "ListenKw" not in pyroflow.__all__
