"""Tests for the data models: ListenerKey, ListenerModel."""

from __future__ import annotations as _annotations

import asyncio

import pytest

import pyroflow.models
from pyroflow.enums import EphemeralUpdates, WorkersBusyMode
from pyroflow.models import ListenerContext, ListenerKey, ListenerModel, WorkersPolicy


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


def test_listener_key_refuses_ephemeral_without_a_user() -> None:
    with pytest.raises(ValueError, match="needs a user_id"):
        ListenerKey(1, None, EphemeralUpdates.ANY)


def test_listener_key_sub_keys_of_an_ephemeral_key_yield_only_itself() -> None:
    key = ListenerKey(1, 2, EphemeralUpdates.ANY)
    assert list(key.sub_keys()) == [key]


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
    model = ListenerModel(ListenerKey(1), fut)
    assert not model.done()
    model.resolve("update")
    assert model.done()
    assert await fut == "update"


async def test_listener_model_set_exc() -> None:
    fut = asyncio.get_running_loop().create_future()
    model = ListenerModel(ListenerKey(1), fut)
    model.set_exc(ValueError("boom"))
    assert model.done()
    with pytest.raises(ValueError):
        await fut


async def test_models_are_slotted() -> None:
    """dataclass(slots=True) is safe unconditionally on the 3.10+ floor:
    no __dict__, unknown attributes rejected."""
    key = ListenerKey(1, 2, 3)
    model = ListenerModel(key, asyncio.get_running_loop().create_future())

    assert model.key == key

    assert not hasattr(model, "__dict__")
    assert not hasattr(key, "__dict__")
    with pytest.raises(AttributeError):
        model.unknown_attr = 1


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


async def test_listener_model_defaults() -> None:
    future = asyncio.get_running_loop().create_future()
    model = ListenerModel(ListenerKey(1), future)
    assert model.future is future
    assert model.context is None
    assert model.filters is None
    assert model.strict is False


# --- ListenerContext ----------------------------------------------------------------


def test_listener_context_fields_default_to_none() -> None:
    context = ListenerContext()
    assert context.message is None
    assert vars(context) == {}


def test_listener_context_reads_added_values_like_its_fields() -> None:
    context = ListenerContext(message="m", step=1)
    context.note = "x"
    assert (context.message, context.step, context.note) == ("m", 1, "x")


def test_listener_context_subclass_declares_fields_with_defaults() -> None:
    class OrderContext(ListenerContext):
        step: int = 0

    assert OrderContext().step == 0
    assert OrderContext(step=2).step == 2
    assert OrderContext(step=2) == OrderContext(step=2)


def test_models_all() -> None:
    assert pyroflow.models.__all__ == (
        "ListenerKey",
        "ListenerContext",
        "ListenerModel",
        "WorkersPolicy",
    )


def test_workers_policy_defaults_to_one_free_worker_and_five_second_timeouts() -> None:
    policy = WorkersPolicy(WorkersBusyMode.REJECT)
    assert (policy.free_workers, policy.busy_timeout, policy.evict_timeout) == (1, 5, 5)


@pytest.mark.parametrize(("free", "busy", "evict"), [(0, 0, 1), (1, -1, 1), (1, 0, 0), (1, 0, -1)])
def test_workers_policy_rejects_invalid_values(free: int, busy: float, evict: float) -> None:
    with pytest.raises(ValueError):
        WorkersPolicy(
            WorkersBusyMode.REJECT, free_workers=free, busy_timeout=busy, evict_timeout=evict
        )
