"""Tests for the data models: ListenerKey, ListenerModel, UpdateRecord."""

from __future__ import annotations as _annotations

import asyncio
import gc
import time
import weakref
from dataclasses import Field

import pytest

import pyroflow.models
from pyroflow.models import ListenerKey, ListenerModel, UpdateRecord, _get_plan, _WeakSlots


def test_listener_key_to_tuple() -> None:
    assert callable(ListenerKey.to_tuple)
    assert ListenerKey(1, 2, 3).to_tuple() == (1, 2, 3)
    assert ListenerKey(1).to_tuple() == (1, None, None)


def test_listener_key_to_dict() -> None:
    assert ListenerKey(1, 2, 3).to_dict() == {"chat_id": 1, "user_id": 2, "message_id": 3}
    assert list(ListenerKey(1).to_dict().items()) == [
        ("chat_id", 1),
        ("user_id", None),
        ("message_id", None),
    ]


def test_listener_key_sub_keys_most_to_least_specific() -> None:
    """Candidates are the combinations of the components present, not just the
    prefixes: (chat, message) is reachable without a user_id."""
    key = ListenerKey(10, 20, 30)
    assert list(key.sub_keys()) == [
        ListenerKey(10, 20, 30),
        ListenerKey(10, 20),
        ListenerKey(10, None, 30),
        ListenerKey(10),
    ]


def test_listener_key_sub_keys_never_repeats_a_key() -> None:
    """Truncating a tuple with trailing Nones used to yield the same key twice,
    costing an extra lookup on every resolve."""
    for key in (
        ListenerKey(10, 20, 30),
        ListenerKey(10, 20),
        ListenerKey(10, None, 30),
        ListenerKey(10),
    ):
        subs = list(key.sub_keys())
        assert len(subs) == len(set(subs)), f"{key} yielded a duplicate"


def test_listener_key_sub_keys_never_invents_a_component() -> None:
    """A key without a user_id must not produce candidates that have one."""
    for sub in ListenerKey(10, None, 30).sub_keys():
        assert sub.user_id is None
        assert sub.chat_id == 10


def test_listener_key_sub_keys_respects_min_dep() -> None:
    key = ListenerKey(10, 20, 30)
    assert list(key.sub_keys(min_dep=2)) == [
        ListenerKey(10, 20, 30),
        ListenerKey(10, 20),
        ListenerKey(10, None, 30),
    ]
    assert list(key.sub_keys(min_dep=3)) == [ListenerKey(10, 20, 30)]


async def test_listener_model_resolve_and_done() -> None:
    fut = asyncio.get_running_loop().create_future()
    model = ListenerModel(ListenerKey(1), None, fut)
    assert not model.done()
    model.resolve("update")
    assert model.done()
    assert await fut == "update"


async def test_listener_model_set_exc() -> None:
    fut = asyncio.get_running_loop().create_future()
    model = ListenerModel(ListenerKey(1), None, fut)
    model.set_exc(ValueError("boom"))
    assert model.done()
    with pytest.raises(ValueError):
        await fut


async def test_models_are_slotted() -> None:
    """dataclass(slots=True) is safe unconditionally on the 3.10+ floor:
    no __dict__, unknown attributes rejected."""
    key = ListenerKey(1, 2, 3)
    # ListenerModel's default `future` field needs a running event loop.
    model = ListenerModel(key)
    rec = UpdateRecord(handler="H")

    assert model.key == key
    assert rec.handler == "H"

    assert not hasattr(model, "__dict__")
    assert not hasattr(key, "__dict__")
    assert not hasattr(rec, "__dict__")
    with pytest.raises(AttributeError):
        model.unknown_attr = 1
    with pytest.raises(AttributeError):
        rec.unknown_attr = 1


def test_get_plan_orders_by_size_then_bit_position() -> None:
    assert _get_plan(0b110) == (0b110, 0b010, 0b100, 0)
    assert _get_plan(0b10) == (0b10, 0)
    assert _get_plan(0b1011) == (
        0b1011,
        0b0011,
        0b1001,
        0b1010,
        0b0001,
        0b0010,
        0b1000,
        0,
    )


def test_listener_key_plans_caches_get_plan_per_mask() -> None:
    list(ListenerKey(1, 2, 3).sub_keys())
    assert 0b110 in ListenerKey.PLANS
    assert ListenerKey.PLANS[0b110] == _get_plan(0b110)
    assert ListenerKey.PLANS[0b110] is ListenerKey.PLANS[0b110]


def test_listener_key_fields_are_the_dataclass_fields_in_order() -> None:
    assert tuple(f.name for f in ListenerKey.FIELDS) == ("chat_id", "user_id", "message_id")
    assert all(isinstance(f, Field) for f in ListenerKey.FIELDS)
    assert ListenerKey.FIELDS is ListenerKey.FIELDS


def test_listener_key_fields_falls_back_to_class_dict_before_dataclass() -> None:
    class Plain:
        FIELDS = "sentinel"

    assert ListenerKey.__dict__["FIELDS"].call(Plain) == "sentinel"


def test_listener_key_sub_keys_rejects_a_missing_chat_id() -> None:
    with pytest.raises(AssertionError, match="chat_id must not be None"):
        list(ListenerKey(None).sub_keys())  # type: ignore[arg-type]


def test_listener_key_sub_keys_chat_only_key_yields_itself() -> None:
    assert list(ListenerKey(1).sub_keys()) == [ListenerKey(1)]
    assert list(ListenerKey(1).sub_keys(min_dep=2)) == []


def test_listener_key_sub_keys_min_dep_bounds() -> None:
    key = ListenerKey(10, 20, 30)
    assert list(key.sub_keys(min_dep=0)) == list(key.sub_keys(min_dep=1))
    assert list(key.sub_keys(min_dep=4)) == []


async def test_listener_model_defaults_bind_to_the_running_loop() -> None:
    model = ListenerModel(ListenerKey(1))
    assert model.meta is None
    assert model.coordinator_id is None
    assert isinstance(model.future, asyncio.Future)
    assert model.future.get_loop() is asyncio.get_running_loop()
    assert ListenerModel(ListenerKey(1)).future is not model.future


def test_weak_slots_adds_only_a_weakref_slot() -> None:
    assert _WeakSlots.__slots__ == ("__weakref__",)
    assert issubclass(UpdateRecord, _WeakSlots)
    rec = UpdateRecord(handler="H")
    ref = weakref.ref(rec)
    assert ref() is rec


def test_update_record_created_at_defaults_to_now() -> None:
    before = time.time()
    rec = UpdateRecord(handler="H")
    assert before <= rec.created_at <= time.time()


def test_update_record_post_init_assigns_increasing_sequence() -> None:
    first = UpdateRecord(handler="H")
    second = UpdateRecord(handler="H")
    assert UpdateRecord._SEQ_IDS[id(first)] < UpdateRecord._SEQ_IDS[id(second)]


def test_update_record_sequence_dropped_when_collected() -> None:
    rec = UpdateRecord(handler="H")
    rec_id = id(rec)
    assert rec_id in UpdateRecord._SEQ_IDS
    del rec
    gc.collect()
    assert rec_id not in UpdateRecord._SEQ_IDS


def test_update_record_orders_ties_by_creation() -> None:
    first = UpdateRecord("H", created_at=1.0)
    second = UpdateRecord("H", created_at=1.0)
    assert first < second
    assert second > first
    assert not second < first
    assert not first > second
    assert not first < first
    assert not first > first


def test_update_record_time_outranks_creation_order() -> None:
    later = UpdateRecord("H", created_at=2.0)
    earlier = UpdateRecord("H", created_at=1.0)
    assert earlier < later
    assert later > earlier
    assert sorted([later, earlier]) == [earlier, later]


def test_models_all() -> None:
    assert pyroflow.models.__all__ == ("ListenerKey", "ListenerModel", "UpdateRecord")
