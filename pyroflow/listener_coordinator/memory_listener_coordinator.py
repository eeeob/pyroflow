"""In-process listener coordinator that keeps registrations in a dict."""

from __future__ import annotations as _annotations
from itertools import count
from typing import TYPE_CHECKING

from ..utils import AsyncioLock
from pytrove import DefaultWeakValueDict
from .listener_coordinator import ListenerCoordinator

import logging

if TYPE_CHECKING:
    from ..models import ListenerKey
    from ..typings import ListenerCoordinatorIdT
    from ..update_listener import UpdateListener
    from .listener_coordinator import LockKeyT

log = logging.getLogger(__name__)


class MemoryListenerCoordinator(ListenerCoordinator):
    """Listener coordinator for a single process, with no shared state."""

    def __init__(self, listener: UpdateListener) -> None:
        """Start with no registrations for ``listener``."""
        super().__init__(listener)

        self.locks: DefaultWeakValueDict[LockKeyT, AsyncioLock] = DefaultWeakValueDict(AsyncioLock)
        self.data: dict[ListenerKey, int] = {}
        self.counter = count()

    def lock(self, key: LockKeyT) -> AsyncioLock:
        """Return the in-process lock for ``key``, created on first use."""
        return self.locks[key]

    def _register(self, key: ListenerKey) -> int:
        if self._registered(key):
            msg = f"Key {key} already registered"
            raise KeyError(msg)

        _id = next(self.counter)
        self.data[key] = _id

        return _id

    def _unregister(
        self, key: ListenerKey, coordinator_id: ListenerCoordinatorIdT | None = None
    ) -> bool:
        if (r_id := self.data.pop(key, None)) is not None:
            if coordinator_id is not None and coordinator_id != r_id:
                self.data[key] = r_id
                return False

        return True

    def _cancel(self, key: ListenerKey) -> bool:
        return self._unregister(key)

    def _registered(
        self, key: ListenerKey, coordinator_id: ListenerCoordinatorIdT | None = None
    ) -> bool:
        if (r_id := self.data.get(key)) is not None:
            return coordinator_id is None or r_id == coordinator_id

        return False

    async def register(self, key: ListenerKey) -> ListenerCoordinatorIdT:
        """Register ``key`` and return its id; raise ``KeyError`` if already taken."""
        return self._register(key)

    async def unregister(
        self, key: ListenerKey, coordinator_id: ListenerCoordinatorIdT | None = None
    ) -> bool:
        """Remove the registration for ``key``, if it matches ``coordinator_id``."""
        return self._unregister(key, coordinator_id)

    async def cancel(self, key: ListenerKey) -> bool:
        """Remove the registration for ``key`` regardless of its id."""
        return self._cancel(key)

    async def registered(
        self, key: ListenerKey, coordinator_id: ListenerCoordinatorIdT | None = None
    ) -> bool:
        """Return whether ``key`` is registered, optionally under ``coordinator_id``."""
        return self._registered(key, coordinator_id)

    async def stop(self) -> None:
        """Reset the id counter and drop every registration, warning if any remain."""
        self.counter = count()

        if self.data:
            log.warning(
                "MemoryListenerCoordinator stopped with pending registrations: %s",
                list(self.data.keys()),
            )

        self.data.clear()
