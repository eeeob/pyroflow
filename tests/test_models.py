"""Tests for the data models: ListenerKey, ListenerModel, UpdateRecord."""

import asyncio

import pytest

from pyroflow.models import ListenerKey, ListenerModel, UpdateRecord


def test_listener_key_to_tuple():
    assert ListenerKey(1, 2, 3).to_tuple == (1, 2, 3)
    assert ListenerKey(1).to_tuple == (1, None, None)


def test_listener_key_sub_keys_most_to_least_specific():
    """Candidates are the combinations of the components present, not just the
    prefixes: (chat, message) is reachable without a user_id."""
    key = ListenerKey(10, 20, 30)
    assert list(key.sub_keys()) == [
        ListenerKey(10, 20, 30),
        ListenerKey(10, 20),
        ListenerKey(10, None, 30),
        ListenerKey(10),
    ]


def test_listener_key_sub_keys_reaches_a_message_only_listener():
    """A listener on (chat, None, message) — "whoever answers *this* message" —
    is registrable, so resolution has to be able to find it. Prefix truncation
    never produced this key, leaving such listeners permanently unmatchable."""
    assert ListenerKey(10, None, 30) in list(ListenerKey(10, 20, 30).sub_keys())


def test_listener_key_sub_keys_never_repeats_a_key():
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


def test_listener_key_sub_keys_never_invents_a_component():
    """A key without a user_id must not produce candidates that have one."""
    for sub in ListenerKey(10, None, 30).sub_keys():
        assert sub.user_id is None
        assert sub.chat_id == 10


def test_listener_key_sub_keys_respects_min_dep():
    key = ListenerKey(10, 20, 30)
    assert list(key.sub_keys(min_dep=2)) == [
        ListenerKey(10, 20, 30),
        ListenerKey(10, 20),
        ListenerKey(10, None, 30),
    ]
    assert list(key.sub_keys(min_dep=3)) == [ListenerKey(10, 20, 30)]


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


async def test_models_are_slotted():
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
