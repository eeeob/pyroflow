"""In-process listener coordinator that keeps registrations in a dict."""

from __future__ import annotations as _annotations

import logging
from itertools import count
from typing import TYPE_CHECKING

from pytrove import DefaultWeakValueDict

from ..utils import AsyncioLock
from .listener_coordinator import ListenerCoordinator

if TYPE_CHECKING:
    from ..models import ListenerKey
    from ..typings import ListenerCoordinatorIdT, LockKeyT
    from ..update_listener import UpdateListener

log = logging.getLogger(__name__)


class MemoryListenerCoordinator(ListenerCoordinator):
    """Listener coordinator for a single process, with no shared state.

    Example:
        >>> import asyncio
        >>> from pyroflow.models import ListenerKey
        >>> async def main():
        ...     coordinator = MemoryListenerCoordinator(listener=None)
        ...     key = ListenerKey(1)
        ...     async with coordinator.lock(key.chat_id):
        ...         coordinator_id = await coordinator.register(key)
        ...         return await coordinator.registered(key, coordinator_id)
        >>> asyncio.run(main())
        True
    """

    def __init__(self, listener: UpdateListener) -> None:
        """Start with no registrations for `listener`."""
        super().__init__(listener)

        self.locks: DefaultWeakValueDict[LockKeyT, AsyncioLock] = DefaultWeakValueDict(AsyncioLock)
        self.data: dict[ListenerKey, int] = {}
        self.counter = count()

    def lock(self, key: LockKeyT) -> AsyncioLock:
        """Return the in-process lock for `key`, created on first use.

        The lock is held weakly, so `key` gets a new one once nothing references
        the previous one.

        Example:
            >>> coordinator = MemoryListenerCoordinator(listener=None)
            >>> lock = coordinator.lock(1)
            >>> lock is coordinator.lock(1), lock is coordinator.lock(2)
            (True, False)
        """
        return self.locks[key]

    def _register(self, key: ListenerKey) -> int:
        """Store `key` under the next id from the counter and return that id.

        Raises:
            KeyError: If `key` is already registered.

        Example:
            >>> from pyroflow.models import ListenerKey
            >>> coordinator = MemoryListenerCoordinator(listener=None)
            >>> coordinator._register(ListenerKey(1)), coordinator._register(ListenerKey(2))
            (0, 1)
            >>> coordinator._register(ListenerKey(1))
            Traceback (most recent call last):
            KeyError: 'Key ListenerKey(chat_id=1, user_id=None, message_id=None) already registered'
        """
        if self._registered(key):
            msg = f"Key {key} already registered"
            raise KeyError(msg)

        _id = next(self.counter)
        self.data[key] = _id

        return _id

    def _unregister(
        self, key: ListenerKey, coordinator_id: ListenerCoordinatorIdT | None = None
    ) -> bool:
        """Drop `key` unless it is registered under an id other than `coordinator_id`.

        Returns:
            `False` only when `key` holds a different id, which is then kept;
            `True` otherwise, including when `key` was not registered.

        Example:
            >>> from pyroflow.models import ListenerKey
            >>> coordinator = MemoryListenerCoordinator(listener=None)
            >>> key = ListenerKey(1)
            >>> coordinator._register(key)
            0
            >>> coordinator._unregister(key, coordinator_id=7)
            False
            >>> coordinator._registered(key)
            True
            >>> coordinator._unregister(key, coordinator_id=0)
            True
            >>> coordinator._registered(key)
            False
        """
        if (r_id := self.data.pop(key, None)) is not None:
            if coordinator_id is not None and coordinator_id != r_id:
                self.data[key] = r_id
                return False

        return True

    def _cancel(self, key: ListenerKey) -> bool:
        """Drop `key` whatever its id; always returns `True`.

        Example:
            >>> from pyroflow.models import ListenerKey
            >>> coordinator = MemoryListenerCoordinator(listener=None)
            >>> coordinator._cancel(ListenerKey(1))
            True
        """
        return self._unregister(key)

    def _registered(
        self, key: ListenerKey, coordinator_id: ListenerCoordinatorIdT | None = None
    ) -> bool:
        """Return whether `key` is stored, and under `coordinator_id` when given.

        Example:
            >>> from pyroflow.models import ListenerKey
            >>> coordinator = MemoryListenerCoordinator(listener=None)
            >>> key = ListenerKey(1)
            >>> coordinator._register(key)
            0
            >>> coordinator._registered(key), coordinator._registered(key, coordinator_id=7)
            (True, False)
        """
        if (r_id := self.data.get(key)) is not None:
            return coordinator_id is None or r_id == coordinator_id

        return False

    async def register(self, key: ListenerKey) -> ListenerCoordinatorIdT:
        """Register `key` and return its id, counting up from `0`.

        Raises:
            KeyError: If `key` is already registered.
        """
        return self._register(key)

    async def unregister(
        self, key: ListenerKey, coordinator_id: ListenerCoordinatorIdT | None = None
    ) -> bool:
        """Remove the registration for `key` if it holds `coordinator_id` when given.

        Returns:
            `False` only when `key` holds a different id; `True` otherwise,
            including when `key` was not registered.
        """
        return self._unregister(key, coordinator_id)

    async def cancel(self, key: ListenerKey) -> bool:
        """Remove the registration for `key` whatever its id; always returns `True`."""
        return self._cancel(key)

    async def registered(
        self, key: ListenerKey, coordinator_id: ListenerCoordinatorIdT | None = None
    ) -> bool:
        """Return whether `key` is registered, under `coordinator_id` when given."""
        return self._registered(key, coordinator_id)

    async def stop(self) -> None:
        """Drop every registration and reset the id counter, warning if any remain.

        Example:
            >>> import asyncio
            >>> from pyroflow.models import ListenerKey
            >>> coordinator = MemoryListenerCoordinator(listener=None)
            >>> coordinator._register(ListenerKey(1))
            0
            >>> asyncio.run(coordinator.stop())
            >>> coordinator.data
            {}
            >>> coordinator._register(ListenerKey(1))
            0
        """
        self.counter = count()

        if self.data:
            log.warning(
                "MemoryListenerCoordinator stopped with pending registrations: %s",
                list(self.data.keys()),
            )

        self.data.clear()


__all__ = ("MemoryListenerCoordinator",)
