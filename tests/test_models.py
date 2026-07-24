"""Tests for the data models: ListenerKey, ListenerModel, UpdateRecord."""

import asyncio

import pytest

from pyroflow.models import ListenerKey, ListenerModel, UpdateRecord


def test_listener_key_to_tuple():
    assert ListenerKey(1, 2, 3).to_tuple == (1, 2, 3)
    assert ListenerKey(1).to_tuple == (1, None, None)


def test_listener_key_sub_keys_most_to_least_specific():
    key = ListenerKey(10, 20, 30)
    assert list(key.sub_keys()) == [
        ListenerKey(10, 20, 30),
        ListenerKey(10, 20),
        ListenerKey(10),
    ]


def test_listener_key_sub_keys_respects_min_dep():
    key = ListenerKey(10, 20, 30)
    assert list(key.sub_keys(min_dep=2)) == [
        ListenerKey(10, 20, 30),
        ListenerKey(10, 20),
    ]


def test_listener_key_hash_and_eq():
    assert ListenerKey(1, 2, 3) == ListenerKey(1, 2, 3)
    assert hash(ListenerKey(1, 2, 3)) == hash(ListenerKey(1, 2, 3))
    assert ListenerKey(1, 2) != ListenerKey(1, 2, 3)
    assert ListenerKey(1, 2, 3) != ("not", "a", "key")
    # usable as dict keys
    d = {ListenerKey(1, 2): "v"}
    assert d[ListenerKey(1, 2)] == "v"


async def test_listener_model_resolve_and_done():
    fut = asyncio.get_running_loop().create_future()
    model = ListenerModel(ListenerKey(1), None, fut)
    assert not model.done()
    model.resolve("update")
    assert model.done()
    assert await fut == "update"


async def test_listener_model_set_exc():
    fut = asyncio.get_running_loop().create_future()
    model = ListenerModel(ListenerKey(1), None, fut)
    model.set_exc(ValueError("boom"))
    assert model.done()
    with pytest.raises(ValueError):
        await fut


def test_update_record_defaults():
    rec = UpdateRecord(handler="H")
    assert rec.handler == "H"
    assert rec.data is None
    assert isinstance(rec.created_at, float)
