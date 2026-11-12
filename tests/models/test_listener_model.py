"""Tests for `pyroflow.models.listener_model`: ListenerContext, ListenerModel."""

from __future__ import annotations as _annotations

import asyncio
import gc

import pytest

from pyroflow.models import ListenerContext, ListenerKey, ListenerModel, MessageKey
from pyroflow.models import listener_model as listener_model_module
from pyroflow.typings import KeyT


def test_logger_name() -> None:
    assert listener_model_module.log.name == "pyroflow.models.listener_model"


# --- ListenerModel ----------------------------------------------------------------------


def test_listener_model_is_generic_over_the_key() -> None:
    assert ListenerModel.__parameters__ == (KeyT,)
    assert ListenerModel[MessageKey] is not ListenerModel


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


@pytest.mark.parametrize("end", ["resolve", "set_exc"])
async def test_listener_model_marked_done_runs_the_callbacks_before_returning(end: str) -> None:
    model = ListenerModel(ListenerKey(1), asyncio.get_running_loop().create_future())
    seen: list[tuple[str, bool]] = []
    model.add_done_callback(lambda m: seen.append(("first", m.done())))
    model.add_done_callback(lambda m: seen.append(("second", m.done())))

    if end == "resolve":
        model.resolve("update")
    else:
        model.set_exc(ValueError("boom"))
        model.future.exception()

    assert seen == [("first", True), ("second", True)]


async def test_listener_model_add_done_callback_passes_the_model() -> None:
    model = ListenerModel(ListenerKey(1), asyncio.get_running_loop().create_future())
    seen: list[ListenerModel] = []
    model.add_done_callback(seen.append)

    model.resolve("update")

    assert seen == [model]


async def test_listener_model_add_done_callback_on_a_done_model_calls_at_once() -> None:
    model = ListenerModel(ListenerKey(1), asyncio.get_running_loop().create_future())
    model.resolve("update")
    seen: list[ListenerModel] = []

    model.add_done_callback(seen.append)

    assert seen == [model]
    assert model.done_callbacks == []


async def test_listener_model_marked_done_twice_does_not_run_the_callbacks_again() -> None:
    model = ListenerModel(ListenerKey(1), asyncio.get_running_loop().create_future())
    seen: list[ListenerModel] = []
    model.add_done_callback(seen.append)
    model.resolve("update")

    with pytest.raises(asyncio.InvalidStateError):
        model.resolve("other")

    with pytest.raises(asyncio.InvalidStateError):
        model.set_exc(ValueError("boom"))

    assert seen == [model]


async def test_listener_model_failing_callback_is_logged_and_the_next_one_runs(
    caplog: pytest.LogCaptureFixture,
) -> None:
    model = ListenerModel(ListenerKey(1), asyncio.get_running_loop().create_future())
    seen: list[ListenerModel] = []

    def fail(_: ListenerModel) -> None:
        msg = "boom"
        raise ValueError(msg)

    model.add_done_callback(fail)
    model.add_done_callback(seen.append)

    model.resolve("update")

    assert seen == [model]
    assert model.done()
    assert "Error in a done callback" in caplog.text


async def test_listener_model_run_done_callbacks_drops_them() -> None:
    model = ListenerModel(ListenerKey(1), asyncio.get_running_loop().create_future())
    seen: list[ListenerModel] = []
    model.done_callbacks.append(seen.append)

    model.run_done_callbacks()
    model.run_done_callbacks()

    assert seen == [model]
    assert model.done_callbacks == []


async def test_listener_model_is_slotted() -> None:
    model = ListenerModel(MessageKey(1, 2), asyncio.get_running_loop().create_future())

    assert model.key == MessageKey(1, 2)
    assert not hasattr(model, "__dict__")
    with pytest.raises(AttributeError):
        model.unknown_attr = 1  # ty: ignore[unresolved-attribute]


async def test_listener_model_defaults() -> None:
    future = asyncio.get_running_loop().create_future()
    model = ListenerModel(ListenerKey(1), future)
    assert model.future is future
    assert model.context is None
    assert model.filters is None
    assert model.strict is False
    assert model.done_callbacks == []
    assert dict(model.declined_updates) == {}
    assert model.on_declined_update is None


async def test_listener_model_decline_notes_the_update_weakly_and_calls_on_decline() -> None:
    model = ListenerModel(MessageKey(1), asyncio.get_running_loop().create_future())
    calls: list[object] = []
    model.on_declined_update = calls.append
    update = ListenerContext()

    model.decline(update)

    assert model.declined_updates[id(update)] is update
    assert calls == [update]

    del update, calls[:]
    gc.collect()

    assert dict(model.declined_updates) == {}


async def test_listener_model_decline_skips_noting_an_update_it_cannot_reference_weakly() -> None:
    model = ListenerModel(MessageKey(1), asyncio.get_running_loop().create_future())

    model.decline("text")

    assert dict(model.declined_updates) == {}


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


def test_listener_model_all() -> None:
    assert listener_model_module.__all__ == ("ListenerContext", "ListenerModel")
