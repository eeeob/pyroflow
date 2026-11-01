"""Tests for ``MessageCoordinated``: its default lock scope and identity."""

from __future__ import annotations as _annotations

from types import SimpleNamespace
from typing import TYPE_CHECKING

import pytest

from pyrogram.raw.types import PeerChannel, PeerChat, PeerUser
from pyrogram.types import Message as PyroMessage
from pyrogram.utils import get_peer_id

from pyroflow import MessageCoordinated
from pyroflow.update_coordinated import message_coordinated
from pyroflow.update_coordinator import MemoryUpdateCoordinator

from ..conftest import make_callback_query

if TYPE_CHECKING:
    from collections.abc import Callable

    from pyrogram.types import Message


async def test_message_coordinated_defaults_lock_per_message(
    raw_message_factory: Callable[..., Message],
) -> None:
    """The shipped default keeps both keys at the update's own granularity,
    so behaviour matches the pre-split library until a scope is chosen."""
    mc = MessageCoordinated()
    msg = raw_message_factory()

    assert await mc.is_coordinatable(msg) is True
    assert await mc.extract_key(msg) == await mc.extract_update_id(msg)


async def test_message_coordinated_lock_flow(raw_message_factory: Callable[..., Message]) -> None:
    mc = MessageCoordinated()
    msg = raw_message_factory()

    lock = await mc.lock(msg)
    assert await lock.acquire() is True
    await lock.release()

    update_id = await mc.extract_update_id(msg)
    assert await mc.coordinator.is_handled(update_id) is False
    await mc.coordinator.mark_handled(update_id)
    assert await mc.coordinator.is_handled(update_id) is True


async def test_extract_key_can_be_widened_without_touching_identity(
    raw_message_factory: Callable[..., Message],
) -> None:
    mc = MessageCoordinated(extract_key_func=lambda u: (get_peer_id(u.raw.peer_id),))
    first = raw_message_factory(message_id=1)
    second = raw_message_factory(message_id=2)

    # Same lock scope...
    assert await mc.extract_key(first) == await mc.extract_key(second)
    # ...but still distinct identities, so neither is dropped as a duplicate.
    assert await mc.extract_update_id(first) != await mc.extract_update_id(second)


def _message(message_id: int = 5, peer: object | None = None) -> Message:
    return PyroMessage(
        id=message_id,
        raw=SimpleNamespace(peer_id=PeerChannel(channel_id=123) if peer is None else peer),
    )


def test_update_type_is_message() -> None:
    assert MessageCoordinated.__update_type__ is PyroMessage


def test_init_defaults_every_callable_to_the_class_hooks() -> None:
    mc = MessageCoordinated()

    assert mc.is_coordinatable_func == mc._is_coordinatable
    assert mc.extract_key_func == mc._extract_key
    assert mc.extract_update_id_func == mc._extract_update_id
    assert isinstance(mc.coordinator, MemoryUpdateCoordinator)
    assert mc.coordinator._update_name == "Message"


def test_init_keeps_the_callables_passed() -> None:
    def is_coordinatable(u: Message) -> bool:
        return False

    def extract_key(u: Message) -> tuple[int]:
        return (1,)

    def extract_update_id(u: Message) -> tuple[int]:
        return (2,)

    mc = MessageCoordinated(
        is_coordinatable_func=is_coordinatable,
        extract_key_func=extract_key,
        extract_update_id_func=extract_update_id,
    )

    assert mc.is_coordinatable_func is is_coordinatable
    assert mc.extract_key_func is extract_key
    assert mc.extract_update_id_func is extract_update_id


def test_init_defaults_only_the_callables_not_passed() -> None:
    def extract_key(u: Message) -> tuple[int]:
        return (1,)

    mc = MessageCoordinated(extract_key_func=extract_key)

    assert mc.extract_key_func is extract_key
    assert mc.is_coordinatable_func == mc._is_coordinatable
    assert mc.extract_update_id_func == mc._extract_update_id


def test_init_forwards_the_coordinator_factory() -> None:
    seen: list[type] = []

    def factory(update_type: type) -> MemoryUpdateCoordinator:
        seen.append(update_type)
        return MemoryUpdateCoordinator(update_type)

    MessageCoordinated(coordinator_factory=factory)

    assert seen == [PyroMessage]


@pytest.mark.parametrize(
    ("peer", "peer_id"),
    [
        (PeerChannel(channel_id=123), -1000000000123),
        (PeerChat(chat_id=55), -55),
        (PeerUser(user_id=77), 77),
    ],
)
async def test_extract_key_is_peer_id_and_message_id(peer: object, peer_id: int) -> None:
    mc = MessageCoordinated()

    assert await mc._extract_key(_message(42, peer)) == (peer_id, 42)
    assert await mc.extract_key(_message(42, peer)) == (peer_id, 42)


@pytest.mark.parametrize(
    ("peer", "peer_id"),
    [
        (PeerChannel(channel_id=123), -1000000000123),
        (PeerChat(chat_id=55), -55),
        (PeerUser(user_id=77), 77),
    ],
)
async def test_extract_update_id_is_peer_id_and_message_id(peer: object, peer_id: int) -> None:
    mc = MessageCoordinated()

    assert await mc._extract_update_id(_message(42, peer)) == (peer_id, 42)
    assert await mc.extract_update_id(_message(42, peer)) == (peer_id, 42)


async def test_default_key_and_identity_are_per_message() -> None:
    mc = MessageCoordinated()
    first = _message(1)
    second = _message(2)
    other_chat = _message(1, PeerChannel(channel_id=999))

    assert await mc.extract_key(first) != await mc.extract_key(second)
    assert await mc.extract_key(first) != await mc.extract_key(other_chat)
    assert await mc.extract_update_id(first) != await mc.extract_update_id(other_chat)
    assert await mc.extract_update_id(first) == await mc.extract_update_id(_message(1))


async def test_extract_key_without_raw_raises() -> None:
    mc = MessageCoordinated()

    with pytest.raises(AttributeError):
        await mc.extract_key(PyroMessage(id=1))
    with pytest.raises(AttributeError):
        await mc.extract_update_id(PyroMessage(id=1))


async def test_is_coordinatable_is_always_true() -> None:
    mc = MessageCoordinated()

    assert await mc._is_coordinatable(_message()) is True
    assert await mc.is_coordinatable(_message()) is True
    assert await mc.is_coordinatable(PyroMessage(id=1)) is True


async def test_public_hooks_reject_non_messages() -> None:
    mc = MessageCoordinated()
    query = make_callback_query()

    for call in (mc.is_coordinatable, mc.extract_key, mc.extract_update_id, mc.lock):
        with pytest.raises(TypeError, match="Expected Message, got CallbackQuery"):
            await call(query)


async def test_widened_key_keeps_the_per_message_identity() -> None:
    mc = MessageCoordinated(extract_key_func=lambda u: (get_peer_id(u.raw.peer_id),))
    first = _message(1)
    second = _message(2)

    assert await mc.extract_key(first) == await mc.extract_key(second) == (-1000000000123,)
    assert await mc.extract_update_id(first) != await mc.extract_update_id(second)


async def test_lock_is_shared_per_message_and_dedupe_tracks_identity() -> None:
    mc = MessageCoordinated()
    message = _message()

    lock = await mc.lock(message)
    assert lock is await mc.lock(_message())
    assert lock is not await mc.lock(_message(6))
    assert await lock.acquire() is True
    await lock.release()

    update_id = await mc.extract_update_id(message)
    assert await mc.coordinator.is_handled(update_id) is False
    await mc.coordinator.mark_handled(update_id)
    assert await mc.coordinator.is_handled(update_id) is True

    await mc.stop()
    assert await mc.coordinator.is_handled(update_id) is False


def test_module_exports_only_the_policy() -> None:
    assert message_coordinated.__all__ == ("MessageCoordinated",)
