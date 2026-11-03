"""Tests for ``MessageCoordinated``: its default lock scope and identity."""

from __future__ import annotations as _annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING

from pyrogram.types import Chat, Message as PyroMessage

from pyroflow import MessageCoordinated
from pyroflow.update_coordinated import message_coordinated
from pyroflow.update_coordinator import MemoryUpdateCoordinator

if TYPE_CHECKING:
    from pyrogram.types import Message


def _message(message_id: int = 5) -> Message:
    return PyroMessage(id=message_id, chat=Chat(id=-1000000000123))


def test_init_defaults_every_callable_to_the_class_hooks() -> None:
    mc = MessageCoordinated()

    assert mc.extract_key_func == mc._extract_key
    assert mc.extract_update_id_func == mc._extract_update_id
    assert isinstance(mc.coordinator, MemoryUpdateCoordinator)
    assert mc.coordinator._update_name == "Message"


def test_init_keeps_the_callables_passed() -> None:
    def extract_key(u: Message) -> tuple[int]:
        return (1,)

    def extract_update_id(u: Message) -> tuple[int]:
        return (2,)

    mc = MessageCoordinated(
        extract_key_func=extract_key,
        extract_update_id_func=extract_update_id,
    )

    assert mc.extract_key_func is extract_key
    assert mc.extract_update_id_func is extract_update_id


def test_init_defaults_only_the_callables_not_passed() -> None:
    def extract_key(u: Message) -> tuple[int]:
        return (1,)

    mc = MessageCoordinated(extract_key_func=extract_key)

    assert mc.extract_key_func is extract_key
    assert mc.extract_update_id_func == mc._extract_update_id


def test_init_forwards_the_coordinator_factory() -> None:
    seen: list[type] = []

    def factory(update_type: type) -> MemoryUpdateCoordinator:
        seen.append(update_type)
        return MemoryUpdateCoordinator(update_type)

    MessageCoordinated(coordinator_factory=factory)

    assert seen == [PyroMessage]


async def test_extract_key_is_the_chat_id() -> None:
    mc = MessageCoordinated()

    assert await mc._extract_key(_message(42)) == (-1000000000123,)
    assert await mc.extract_key(_message(42)) == await mc.extract_key(_message(43))


async def test_extract_key_leaves_a_message_without_a_chat_uncoordinated() -> None:
    assert await MessageCoordinated()._extract_key(PyroMessage(id=1)) is None


async def test_extract_update_id_is_chat_id_message_id_and_zero_before_an_edit() -> None:
    mc = MessageCoordinated()

    assert await mc._extract_update_id(_message(42)) == (-1000000000123, 42, 0)


async def test_extract_update_id_tells_an_edit_from_the_original_and_other_edits() -> None:
    mc = MessageCoordinated()
    original = _message(42)
    edited = _message(42)
    edited.edit_date = datetime(2026, 1, 1, tzinfo=timezone.utc)
    edited_again = _message(42)
    edited_again.edit_date = datetime(2026, 1, 2, tzinfo=timezone.utc)

    ids = {await mc.extract_update_id(m) for m in (original, edited, edited_again)}

    assert len(ids) == 3
    assert await mc.extract_update_id(edited) == (
        -1000000000123,
        42,
        int(edited.edit_date.timestamp()),
    )


async def test_narrowed_key_locks_per_message() -> None:
    mc = MessageCoordinated(extract_key_func=lambda u: (u.chat.id, u.id))

    assert await mc.extract_key(_message(1)) != await mc.extract_key(_message(2))


def test_module_exports_only_the_policy() -> None:
    assert message_coordinated.__all__ == ("MessageCoordinated",)
