"""Tests for ``pyroflow.listener_coordinator.listener_coordinator``."""

from __future__ import annotations as _annotations

from typing import Any

import pytest

from pyroflow.listener_coordinator import listener_coordinator as module
from pyroflow.listener_coordinator.listener_coordinator import ListenerCoordinator
from pyroflow.models import ListenerKey

KEY = ListenerKey(1, 2)


class _Concrete(ListenerCoordinator):
    """Smallest concrete subclass; every method defers to the abstract body."""

    def lock(self, key: Any) -> Any:
        return super().lock(key)

    async def register(self, key: ListenerKey) -> Any:
        return await super().register(key)

    async def unregister(self, key: ListenerKey, coordinator_id: Any = None) -> bool:
        return await super().unregister(key, coordinator_id)

    async def cancel(self, key: ListenerKey) -> bool:
        return await super().cancel(key)

    async def registered(self, key: ListenerKey, coordinator_id: Any = None) -> bool:
        return await super().registered(key, coordinator_id)


def test_module_exports_only_the_base_class() -> None:
    assert module.__all__ == ("ListenerCoordinator",)


def test_abstract_methods_are_the_backend_contract() -> None:
    assert ListenerCoordinator.__abstractmethods__ == frozenset(
        {"lock", "register", "unregister", "cancel", "registered"}
    )


def test_init_forwards_extra_kwargs_along_the_mro() -> None:
    class _Mixin:
        def __init__(self, extra: int, **kw: Any) -> None:
            super().__init__(**kw)
            self.extra = extra

    class _WithMixin(_Concrete, _Mixin):
        pass

    coordinator = _WithMixin(listener=None, extra=3)  # type: ignore[arg-type]
    assert coordinator.extra == 3
    assert coordinator.listener is None


@pytest.mark.parametrize("name", ["register", "unregister", "cancel", "registered"])
async def test_abstract_bodies_raise_not_implemented(name: str) -> None:
    coordinator = _Concrete(None)  # type: ignore[arg-type]
    with pytest.raises(NotImplementedError):
        coordinator.lock(KEY)
    with pytest.raises(NotImplementedError):
        await getattr(coordinator, name)(KEY)


async def test_start_is_a_no_op_by_default() -> None:
    coordinator = _Concrete(None)  # type: ignore[arg-type]
    before = dict(vars(coordinator))
    assert await coordinator.start() is None
    assert vars(coordinator) == before


async def test_stop_is_a_no_op_by_default() -> None:
    coordinator = _Concrete(None)  # type: ignore[arg-type]
    before = dict(vars(coordinator))
    assert await coordinator.stop() is None
    assert await coordinator.stop() is None
    assert vars(coordinator) == before
