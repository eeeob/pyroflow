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


async def test_models_still_instantiate_and_reject_unknown_attrs_when_slotted():
    """Regression guard for the C5 CI failure: dataclass(slots=True) is
    3.10+ only. models.py must build the ``slots`` kwarg conditionally
    (via a dict passed as ``**_SLOTS_KW``) rather than passing a literal
    ``slots=`` keyword, so it never crashes on import on Python 3.9."""
    import sys

    key = ListenerKey(1, 2, 3)
    # ListenerModel's default `future` field needs a running event loop.
    model = ListenerModel(key)
    rec = UpdateRecord(handler="H")

    # Basic behaviour must hold regardless of whether slots were applied.
    assert model.key == key
    assert rec.handler == "H"

    if sys.version_info >= (3, 10):
        # slots=True actually took effect: no __dict__, unknown attrs rejected.
        assert not hasattr(model, "__dict__")
        with pytest.raises(AttributeError):
            model.unknown_attr = 1
        with pytest.raises(AttributeError):
            rec.unknown_attr = 1
    # On < 3.10 the fallback drops slots silently; only import/behaviour is
    # asserted above (no __dict__ absence claim from the constructor mock).
