"""Tests for the coordinator base class: key building and the defaults every
backend inherits, exercised through the in-memory backend."""

from __future__ import annotations as _annotations

from typing import Any, get_args, TYPE_CHECKING

import pytest

from pyrogram.types import CallbackQuery, Message
from pytrove.enums import TimeUnit

from pyroflow.typings import UpdateCoordinatorSectionT
from pyroflow.update_coordinator import update_coordinator
from pyroflow.update_coordinator.memory_update_coordinator import (
    MemoryUpdateCoordinator,
)
from pyroflow.update_coordinator.update_coordinator import UpdateCoordinator

if TYPE_CHECKING:
    from pyroflow.typings import AsyncLockProto, UpdateCoordinatorKeyT


def _coord(**kw: float) -> MemoryUpdateCoordinator:
    kw.setdefault("blocking_timeout", 0.05)
    return MemoryUpdateCoordinator(Message, **kw)


def test_lock_and_handled_build_distinct_keys() -> None:
    coord = _coord()
    assert coord.build_key((1, 2), "lock") != coord.build_key((1, 2), "handled")


def test_build_key_namespaces_by_update_type() -> None:
    assert MemoryUpdateCoordinator(Message).build_key((1,)) != MemoryUpdateCoordinator(
        type("Other", (Message,), {})
    ).build_key((1,))


# --- liveness (audit finding H1) -----------------------------------------


def test_blocking_timeout_default_is_short() -> None:
    """The dispatcher waits on the lock while holding its worker lock, so a
    contended update stalls every other update on that worker for the full
    timeout. The default must stay small."""
    coordinator = MemoryUpdateCoordinator(Message)

    assert coordinator.blocking_timeout <= 30, (
        f"blocking_timeout default is {coordinator.blocking_timeout}s — a "
        f"contended update would stall a whole worker for that long"
    )


# --- the base class itself, through a minimal concrete stub ---------------


class _Stub(UpdateCoordinator):
    """Reaches the abstract bodies through `super()` to pin their contract."""

    def lock(self, key: UpdateCoordinatorKeyT) -> AsyncLockProto:
        return super().lock(key)  # type: ignore[safe-super]

    async def is_handled(self, key: UpdateCoordinatorKeyT) -> bool:
        return await super().is_handled(key)  # type: ignore[safe-super]

    async def mark_handled(self, key: UpdateCoordinatorKeyT) -> None:
        await super().mark_handled(key)  # type: ignore[safe-super]


def test_base_class_cannot_be_instantiated() -> None:
    with pytest.raises(TypeError):
        UpdateCoordinator(Message)  # type: ignore[abstract]


def test_init_defaults() -> None:
    coord = _Stub(Message)

    assert coord.lock_ttl == TimeUnit.HOUR == 3600
    assert coord.handled_ttl == TimeUnit.HOUR
    assert coord.blocking_timeout == 5


def test_init_stores_explicit_values() -> None:
    coord = _Stub(Message, lock_ttl=10, handled_ttl=0.5, blocking_timeout=0.1)

    assert (coord.lock_ttl, coord.handled_ttl, coord.blocking_timeout) == (10, 0.5, 0.1)


def test_init_forwards_extra_kwargs_along_the_mro() -> None:
    class _Mixin:
        def __init__(self, *, extra: int, **kw: Any) -> None:
            self.extra = extra
            super().__init__(**kw)

    class _WithMixin(_Stub, _Mixin):
        pass

    assert _WithMixin(Message, extra=7).extra == 7


def test_init_rejects_unknown_kwargs() -> None:
    with pytest.raises(TypeError):
        _Stub(Message, unknown=1)


def test_key_formats_cover_every_section() -> None:
    assert set(_Stub(Message)._key_formats) == set(get_args(UpdateCoordinatorSectionT))


def test_build_key_renders_each_section_exactly() -> None:
    coord = _Stub(Message)

    assert coord.build_key((-100123, 42), "lock") == "update|lock|Message|-100123|42"
    assert coord.build_key((-100123, 42), "handled") == "update|handled|Message|-100123|42"


def test_build_key_defaults_to_the_lock_section() -> None:
    coord = _Stub(Message)
    assert coord.build_key((1, 2)) == coord.build_key((1, 2), "lock")


def test_build_key_uses_the_update_type_name() -> None:
    assert _Stub(CallbackQuery).build_key((1,)) == "update|lock|CallbackQuery|1"


def test_build_key_stringifies_str_components() -> None:
    assert _Stub(Message).build_key(("abc", 1)) == "update|lock|Message|abc|1"


def test_build_key_of_an_empty_tuple() -> None:
    assert _Stub(Message).build_key(()) == "update|lock|Message|"


def test_build_key_rejects_an_unknown_section() -> None:
    with pytest.raises(KeyError):
        _Stub(Message).build_key((1,), "other")  # type: ignore[arg-type]


def test_abstract_lock_body_raises() -> None:
    with pytest.raises(NotImplementedError):
        _Stub(Message).lock((1,))


async def test_abstract_is_handled_body_raises() -> None:
    with pytest.raises(NotImplementedError):
        await _Stub(Message).is_handled((1,))


async def test_abstract_mark_handled_body_raises() -> None:
    with pytest.raises(NotImplementedError):
        await _Stub(Message).mark_handled((1,))


async def test_start_and_stop_are_no_ops() -> None:
    coord = _Stub(Message, lock_ttl=10)

    assert await coord.start() is None
    assert await coord.stop() is None
    assert coord.lock_ttl == 10


def test_all_exports_only_the_base_class() -> None:
    assert update_coordinator.__all__ == ("UpdateCoordinator",)
