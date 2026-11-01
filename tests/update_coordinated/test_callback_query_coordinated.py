"""Tests for ``CallbackQueryCoordinated``: coordinatability, keys and locking."""

from __future__ import annotations as _annotations

import pytest

from pyrogram.types import CallbackQuery

from pyroflow import CallbackQueryCoordinated
from pyroflow.update_coordinated import callback_query_coordinated
from pyroflow.update_coordinator import MemoryUpdateCoordinator

from ..conftest import make_callback_query, make_message


async def test_callback_coordinated_is_coordinatable_returns_true() -> None:
    """Regression guard for C3: a missing ``return`` made this yield None,
    silently disabling CallbackQuery coordination entirely."""
    cc = CallbackQueryCoordinated()
    result = await cc.is_coordinatable(make_callback_query())

    assert result is True, (
        "CallbackQueryCoordinated._is_coordinatable must RETURN True (audit finding C3 regression)"
    )


async def test_callback_coordinated_keys() -> None:
    cc = CallbackQueryCoordinated()
    cbq = make_callback_query()

    assert await cc.extract_key(cbq) == (cbq.id,)
    assert await cc.extract_update_id(cbq) == (cbq.id,)


async def test_callback_coordinated_lock_flow() -> None:
    cc = CallbackQueryCoordinated()
    cbq = make_callback_query()

    lock = await cc.lock(cbq)
    assert await lock.acquire() is True
    await lock.release()
    assert await (await cc.lock(cbq)).acquire() is True


def test_update_type_is_callback_query() -> None:
    assert CallbackQueryCoordinated.__update_type__ is CallbackQuery


def test_init_defaults_every_callable_to_the_class_hooks() -> None:
    cc = CallbackQueryCoordinated()

    assert cc.is_coordinatable_func == cc._is_coordinatable
    assert cc.extract_key_func == cc._extract_key
    assert cc.extract_update_id_func == cc._extract_update_id
    assert isinstance(cc.coordinator, MemoryUpdateCoordinator)
    assert cc.coordinator._update_name == "CallbackQuery"


def test_init_keeps_the_callables_passed() -> None:
    def is_coordinatable(u: CallbackQuery) -> bool:
        return False

    def extract_key(u: CallbackQuery) -> tuple[int]:
        return (1,)

    def extract_update_id(u: CallbackQuery) -> tuple[int]:
        return (2,)

    cc = CallbackQueryCoordinated(
        is_coordinatable_func=is_coordinatable,
        extract_key_func=extract_key,
        extract_update_id_func=extract_update_id,
    )

    assert cc.is_coordinatable_func is is_coordinatable
    assert cc.extract_key_func is extract_key
    assert cc.extract_update_id_func is extract_update_id


def test_init_defaults_only_the_callables_not_passed() -> None:
    def extract_key(u: CallbackQuery) -> tuple[int]:
        return (1,)

    cc = CallbackQueryCoordinated(extract_key_func=extract_key)

    assert cc.extract_key_func is extract_key
    assert cc.is_coordinatable_func == cc._is_coordinatable
    assert cc.extract_update_id_func == cc._extract_update_id


def test_init_forwards_the_coordinator_factory() -> None:
    seen: list[type] = []

    def factory(update_type: type) -> MemoryUpdateCoordinator:
        seen.append(update_type)
        return MemoryUpdateCoordinator(update_type)

    CallbackQueryCoordinated(coordinator_factory=factory)

    assert seen == [CallbackQuery]


async def test_private_hooks_use_the_query_id() -> None:
    cc = CallbackQueryCoordinated()
    query = make_callback_query(id="q-42")

    assert await cc._extract_key(query) == ("q-42",)
    assert await cc._extract_update_id(query) == ("q-42",)
    assert await cc._is_coordinatable(query) is True


async def test_default_key_ignores_chat_and_user() -> None:
    cc = CallbackQueryCoordinated()
    same_user = make_callback_query(id="a")
    other = make_callback_query(id="b")
    same_id_other_chat = make_callback_query(chat_id=999, user_id=1, id="a")

    assert await cc.extract_key(same_user) != await cc.extract_key(other)
    assert await cc.extract_key(same_user) == await cc.extract_key(same_id_other_chat)
    assert await cc.extract_update_id(same_user) == await cc.extract_update_id(same_id_other_chat)


async def test_is_coordinatable_without_message_or_data() -> None:
    cc = CallbackQueryCoordinated()
    query = make_callback_query(message=None, data=None)

    assert await cc.is_coordinatable(query) is True


async def test_public_hooks_reject_non_callback_queries() -> None:
    cc = CallbackQueryCoordinated()
    message = make_message()

    for call in (cc.is_coordinatable, cc.extract_key, cc.extract_update_id, cc.lock):
        with pytest.raises(TypeError, match="Expected CallbackQuery, got Message"):
            await call(message)


async def test_widened_key_keeps_the_per_query_identity() -> None:
    cc = CallbackQueryCoordinated(extract_key_func=lambda q: (q.from_user.id,))
    first = make_callback_query(id="a")
    second = make_callback_query(id="b")

    assert await cc.extract_key(first) == await cc.extract_key(second) == (7,)
    assert await cc.extract_update_id(first) != await cc.extract_update_id(second)


async def test_lock_is_shared_per_query_and_dedupe_tracks_identity() -> None:
    cc = CallbackQueryCoordinated()
    query = make_callback_query(id="a")

    lock = await cc.lock(query)
    assert lock is await cc.lock(make_callback_query(id="a"))
    assert lock is not await cc.lock(make_callback_query(id="b"))

    update_id = await cc.extract_update_id(query)
    await cc.coordinator.mark_handled(update_id)
    assert await cc.coordinator.is_handled(update_id) is True
    assert await cc.coordinator.is_handled(("b",)) is False


def test_module_exports_only_the_policy() -> None:
    assert callback_query_coordinated.__all__ == ("CallbackQueryCoordinated",)
