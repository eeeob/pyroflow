"""Tests for ``CallbackQueryCoordinated``: its default lock key and identity."""

from __future__ import annotations as _annotations

from pyrogram.types import CallbackQuery

from pyroflow import CallbackQueryCoordinated
from pyroflow.update_coordinated import callback_query_coordinated
from pyroflow.update_coordinator import MemoryUpdateCoordinator

from ..conftest import make_callback_query


async def test_callback_coordinated_keys() -> None:
    cc = CallbackQueryCoordinated()
    cbq = make_callback_query(chat_id=100)

    assert await cc.extract_key(cbq) == (100,)
    assert await cc.extract_update_id(cbq) == (cbq.id,)


def test_init_defaults_every_callable_to_the_class_hooks() -> None:
    cc = CallbackQueryCoordinated()

    assert cc.extract_key_func == cc._extract_key
    assert cc.extract_update_id_func == cc._extract_update_id
    assert isinstance(cc.coordinator, MemoryUpdateCoordinator)
    assert cc.coordinator.update_type is CallbackQuery


def test_init_keeps_the_callables_passed() -> None:
    def extract_key(u: CallbackQuery) -> tuple[int]:
        return (1,)

    def extract_update_id(u: CallbackQuery) -> tuple[int]:
        return (2,)

    cc = CallbackQueryCoordinated(
        extract_key_func=extract_key,
        extract_update_id_func=extract_update_id,
    )

    assert cc.extract_key_func is extract_key
    assert cc.extract_update_id_func is extract_update_id


def test_init_defaults_only_the_callables_not_passed() -> None:
    def extract_key(u: CallbackQuery) -> tuple[int]:
        return (1,)

    cc = CallbackQueryCoordinated(extract_key_func=extract_key)

    assert cc.extract_key_func is extract_key
    assert cc.extract_update_id_func == cc._extract_update_id


def test_init_keeps_the_given_coordinator() -> None:
    coordinator = MemoryUpdateCoordinator(CallbackQueryCoordinated.__update_type__)

    assert CallbackQueryCoordinated(coordinator=coordinator).coordinator is coordinator


async def test_private_extract_key_is_the_message_chat() -> None:
    cc = CallbackQueryCoordinated()

    assert await cc._extract_key(make_callback_query(chat_id=-100, id="q-42")) == (-100,)


async def test_private_extract_key_leaves_a_query_without_a_message_uncoordinated() -> None:
    cc = CallbackQueryCoordinated()

    assert await cc._extract_key(make_callback_query(id="q-42", message=None)) is None


async def test_private_extract_update_id_is_the_query_id() -> None:
    cc = CallbackQueryCoordinated()

    assert await cc._extract_update_id(make_callback_query(id="q-42")) == ("q-42",)


async def test_widened_key_keeps_the_per_query_identity() -> None:
    cc = CallbackQueryCoordinated(extract_key_func=lambda q: (q.from_user.id,))
    first = make_callback_query(id="a")
    second = make_callback_query(id="b")

    assert await cc.extract_key(first) == await cc.extract_key(second) == (7,)
    assert await cc.extract_update_id(first) != await cc.extract_update_id(second)


def test_module_exports_only_the_policy() -> None:
    assert callback_query_coordinated.__all__ == ("CallbackQueryCoordinated",)
