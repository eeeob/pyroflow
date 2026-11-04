"""Tests for the coordinator base class: the defaults every backend inherits."""

from __future__ import annotations as _annotations

from typing import Any, TYPE_CHECKING

import pytest

from pyrogram.types import Message
from pytrove.enums import TimeUnit

from pyroflow.models import ListenerKey
from pyroflow.update_coordinator import update_coordinator
from pyroflow.update_coordinator.update_coordinator import UpdateCoordinator

if TYPE_CHECKING:
    from collections.abc import Sequence

    from pyroflow.typings import AsyncLockProto, CoordinatedUpdateKeyT, CoordinatedUpdateIdT


# --- the base class itself, through a minimal concrete stub ---------------


class _Stub(UpdateCoordinator):
    """Reaches the abstract bodies through `super()` to pin their contract."""

    def lock(self, key: CoordinatedUpdateKeyT) -> AsyncLockProto:
        return super().lock(key)  # type: ignore[safe-super]

    async def is_handled(self, key: CoordinatedUpdateIdT) -> bool:
        return await super().is_handled(key)  # type: ignore[safe-super]

    async def mark_handled(self, key: CoordinatedUpdateIdT) -> None:
        await super().mark_handled(key)  # type: ignore[safe-super]

    async def register_listener(
        self, key: ListenerKey, owner_id: str, *, replace: bool
    ) -> str | None:
        return await super().register_listener(key, owner_id, replace=replace)  # type: ignore[safe-super]

    async def listener_owners(self, keys: Sequence[ListenerKey]) -> list[str | None]:
        return await super().listener_owners(keys)  # type: ignore[safe-super]

    async def unregister_listener(self, key: ListenerKey, owner_id: str) -> bool:
        return await super().unregister_listener(key, owner_id)  # type: ignore[safe-super]

    async def cancel_listener(self, key: ListenerKey) -> str | None:
        return await super().cancel_listener(key)  # type: ignore[safe-super]


def test_init_defaults() -> None:
    coord = _Stub(Message)

    assert coord.update_type is Message
    assert coord.handled_ttl == TimeUnit.HOUR
    assert coord.blocking_timeout == 10
    assert coord.on_listener_lost is None


def test_init_gives_each_coordinator_its_own_fingerprint() -> None:
    first, second = _Stub(Message), _Stub(Message)

    assert len(first.fingerprint) == 32
    int(first.fingerprint, 16)
    assert first.fingerprint != second.fingerprint


def test_new_owner_id_is_the_fingerprint_and_a_fresh_suffix() -> None:
    coord = _Stub(Message)
    first, second = coord.new_owner_id(), coord.new_owner_id()

    assert first.startswith(f"{coord.fingerprint}:")
    assert first != second


def test_is_mine_tells_own_ids_from_a_peer() -> None:
    coord, peer = _Stub(Message), _Stub(Message)

    assert coord.is_mine(coord.new_owner_id()) is True
    assert coord.is_mine(peer.new_owner_id()) is False
    assert coord.is_mine(coord.fingerprint) is False


def test_init_stores_explicit_values() -> None:
    coord = _Stub(Message, handled_ttl=0.5, blocking_timeout=0.1)

    assert (coord.handled_ttl, coord.blocking_timeout) == (0.5, 0.1)


def test_init_forwards_extra_kwargs_along_the_mro() -> None:
    class _Mixin:
        def __init__(self, *, extra: int, **kw: Any) -> None:
            self.extra = extra
            super().__init__(**kw)

    class _WithMixin(_Stub, _Mixin):
        pass

    assert _WithMixin(Message, extra=7).extra == 7


@pytest.mark.parametrize("name", ["is_handled", "mark_handled"])
async def test_abstract_bodies_raise_not_implemented(name: str) -> None:
    coord = _Stub(Message)
    with pytest.raises(NotImplementedError):
        coord.lock((1,))
    with pytest.raises(NotImplementedError):
        await getattr(coord, name)((1,))


async def test_abstract_listener_bodies_raise_not_implemented() -> None:
    coord = _Stub(Message)
    key = ListenerKey(1)

    with pytest.raises(NotImplementedError):
        await coord.register_listener(key, "a", replace=False)
    with pytest.raises(NotImplementedError):
        await coord.listener_owners([key])
    with pytest.raises(NotImplementedError):
        await coord.unregister_listener(key, "a")
    with pytest.raises(NotImplementedError):
        await coord.cancel_listener(key)


async def test_start_and_stop_are_no_ops() -> None:
    coord = _Stub(Message)

    assert await coord.start() is None
    assert await coord.stop() is None


def test_all_exports_only_the_base_class() -> None:
    assert update_coordinator.__all__ == ("UpdateCoordinator",)
