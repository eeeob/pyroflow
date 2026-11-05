"""Tests for `pyroflow.utils.helpers`: `UpdateBound`, `get_update_executor` and `subsets_largest_first`."""

from __future__ import annotations as _annotations

from abc import ABC
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
from typing import Any

import pytest

from pyroflow.utils import (
    UpdateBound,
    get_update_executor,
    helpers,
    subsets_largest_first,
)
from pyrogram.types import Message


# --- UpdateBound ----------------------------------------------------------


def test_update_bound_rejects_non_update_type() -> None:
    with pytest.raises(TypeError):

        class BadType(UpdateBound):  # pragma: no cover - class body raises
            __update_type__ = int


# --- _check_update_type ----------------------------------------------------


def test_check_update_type_accepts_a_pyrogram_update_class() -> None:
    assert helpers._check_update_type(type("Good", (), {"__update_type__": Message})) is None


@pytest.mark.parametrize(
    ("update_type", "message"),
    [
        (None, "Bad must define __update_type__"),
        (int, "Bad.__update_type__ must be a subclass of Update"),
        (Message(id=1), "Bad.__update_type__ must be a subclass of Update"),
    ],
)
def test_check_update_type_rejects_a_missing_or_wrong_type(
    update_type: object, message: str
) -> None:
    with pytest.raises(TypeError, match=message):
        helpers._check_update_type(type("Bad", (), {"__update_type__": update_type}))


# --- UpdateBound: more branches ------------------------------------------


def test_update_bound_missing_type_message() -> None:
    with pytest.raises(TypeError, match="Missing must define __update_type__"):

        class Missing(UpdateBound):  # pragma: no cover - class body raises
            pass


def test_update_bound_rejects_an_update_instance() -> None:
    with pytest.raises(TypeError, match=r"__update_type__ must be a subclass of Update"):

        class Instance(UpdateBound):  # pragma: no cover - class body raises
            __update_type__ = Message(id=1)


def test_update_bound_abc_exemption_needs_abc_as_a_direct_base() -> None:
    class Abstract(ABC, UpdateBound):
        pass

    with pytest.raises(TypeError, match="must define __update_type__"):

        class Concrete(Abstract):  # pragma: no cover - class body raises
            pass


def test_update_bound_subclass_inherits_update_type() -> None:
    class Good(UpdateBound):
        __update_type__ = Message

    class Child(Good):
        pass

    assert Child.__update_type__ is Message


def test_update_bound_init_subclass_forwards_kwargs() -> None:
    seen: dict[str, Any] = {}

    class Recorder:
        def __init_subclass__(cls, **kw: Any) -> None:
            seen.update(kw)
            super().__init_subclass__()

    class Good(UpdateBound, Recorder, flag=True):
        __update_type__ = Message

    assert seen == {"flag": True}


def test_update_bound_init_passes_kwargs_to_the_next_base() -> None:
    class Store:
        def __init__(self, **kw: Any) -> None:
            self.kw = kw

    class Good(UpdateBound, Store):
        __update_type__ = Message

    assert Good(a=1).kw == {"a": 1}


def test_update_bound_init_rejects_an_abstract_subclass_without_type() -> None:
    class Abstract(ABC, UpdateBound):
        pass

    with pytest.raises(TypeError, match="Abstract must define __update_type__"):
        Abstract()


def test_update_bound_init_rejects_a_type_replaced_after_definition() -> None:
    class Good(UpdateBound):
        __update_type__ = Message

    Good.__update_type__ = int  # type: ignore[assignment]

    with pytest.raises(TypeError, match=r"Good.__update_type__ must be a subclass of Update"):
        Good()


def test_validate_update_accepts_a_subclass_instance() -> None:
    class SubMessage(Message):
        pass

    class Good(UpdateBound):
        __update_type__ = Message

    Good.validate_update(SubMessage(id=1))


def test_validate_update_error_message() -> None:
    class Good(UpdateBound):
        __update_type__ = Message

    with pytest.raises(TypeError, match="Expected Message, got str"):
        Good.validate_update("text")


# --- get_update_executor ----------------------------------------------------


def test_get_update_executor_returns_the_client_executor() -> None:
    executor = ThreadPoolExecutor(max_workers=1)
    try:
        update = SimpleNamespace(_client=SimpleNamespace(executor=executor))
        assert get_update_executor(update) is executor
    finally:
        executor.shutdown()


def test_get_update_executor_without_client() -> None:
    assert get_update_executor(SimpleNamespace()) is None


def test_get_update_executor_client_without_executor() -> None:
    assert get_update_executor(SimpleNamespace(_client=SimpleNamespace())) is None


def test_subsets_largest_first_goes_from_all_items_to_none_in_item_order() -> None:
    assert list(subsets_largest_first("abc")) == [
        ("a", "b", "c"),
        ("a", "b"),
        ("a", "c"),
        ("b", "c"),
        ("a",),
        ("b",),
        ("c",),
        (),
    ]


def test_subsets_largest_first_of_nothing_is_the_empty_subset() -> None:
    assert list(subsets_largest_first([])) == [()]


def test_handler_worker_var_is_unset_outside_a_worker() -> None:
    assert helpers.handler_worker_var.get() is None


def test_module_all_lists_public_names() -> None:
    assert helpers.__all__ == (
        "handler_worker_var",
        "UpdateBound",
        "get_update_executor",
        "subsets_largest_first",
    )
