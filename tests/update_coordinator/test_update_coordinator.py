"""Tests for the coordinator base class: the defaults every backend inherits."""

from __future__ import annotations as _annotations

from typing import Any, TYPE_CHECKING

import pytest

from pyrogram.types import Message
from pytrove.enums import TimeUnit

from pyroflow.update_coordinator import update_coordinator
from pyroflow.update_coordinator.update_coordinator import UpdateCoordinator

if TYPE_CHECKING:
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


def test_init_defaults() -> None:
    coord = _Stub(Message)

    assert coord.update_type is Message
    assert coord.handled_ttl == TimeUnit.HOUR
    assert coord.blocking_timeout == 10


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


async def test_start_and_stop_are_no_ops() -> None:
    coord = _Stub(Message)

    assert await coord.start() is None
    assert await coord.stop() is None


def test_all_exports_only_the_base_class() -> None:
    assert update_coordinator.__all__ == ("UpdateCoordinator",)
