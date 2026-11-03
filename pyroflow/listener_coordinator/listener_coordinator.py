"""Abstract base class shared by every listener coordinator backend."""

from __future__ import annotations as _annotations

from abc import ABC, abstractmethod
from typing import Any, TYPE_CHECKING


if TYPE_CHECKING:
    from ..models import ListenerKey
    from ..typings import AsyncLockProto, ListenerCoordinatorIdT
    from ..update_listener import UpdateListener


class ListenerCoordinator(ABC):
    """Abstract base for the registry that tracks listener registrations.

    The caller serialises operations on a chat under `lock(key.chat_id)`:
    `UpdateListener` already holds it when it calls `register`, `unregister`,
    `cancel` and `registered`. The lock is not reentrant, so taking it again
    inside those methods deadlocks the worker. Guard state the lock does not
    cover, such as a pool shared across chats, with a separate lock.
    """

    def __init__(self, listener: UpdateListener, **kw: Any) -> None:
        """Bind the coordinator to the listener that owns it.

        Args:
            listener: The `UpdateListener` that owns this coordinator.
            **kw: Passed to the next class in the MRO.
        """
        super().__init__(**kw)

        self.listener = listener
        """The listener whose registrations this coordinator tracks."""

    @abstractmethod
    def lock(self, key: ListenerKey) -> AsyncLockProto:
        """Return the async lock that serialises coordinator operations for `key`.

        Args:
            key: A chat id, a tuple of ids or a `ListenerKey` naming the scope.

        Returns:
            An async lock usable with `async with`.
        """
        raise NotImplementedError

    @abstractmethod
    async def register(self, key: ListenerKey) -> ListenerCoordinatorIdT:
        """Register a listener for `key`.

        Args:
            key: The key to register.

        Returns:
            A unique id; passing it to `unregister` removes this registration
            without removing a newer one for the same key.

        Raises:
            KeyError: If `key` is already registered.
        """
        raise NotImplementedError

    @abstractmethod
    async def unregister(
        self, key: ListenerKey, coordinator_id: ListenerCoordinatorIdT | None = None
    ) -> bool:
        """Remove the registration for `key`.

        Args:
            key: The key to unregister.
            coordinator_id: When given, remove the registration only if it
                holds this id, so a newer one for the same key survives.

        Returns:
            `False` only when `coordinator_id` is given and `key` holds a
            different id; `True` otherwise, including when `key` was not
            registered. Redis without `coordinator_id` returns whether a key
            was deleted.
        """
        raise NotImplementedError

    @abstractmethod
    async def cancel(self, key: ListenerKey) -> bool:
        """Cancel every registration for `key`, whatever its id.

        Args:
            key: The key to cancel.

        Returns:
            Backend-specific: Redis returns whether a registration existed,
            Memory always returns `True`. Either way `key` is no longer
            registered afterwards.
        """
        raise NotImplementedError

    @abstractmethod
    async def registered(
        self, key: ListenerKey, coordinator_id: ListenerCoordinatorIdT | None = None
    ) -> bool:
        """Return whether `key` is registered.

        Args:
            key: The key to check.
            coordinator_id: When given, also require the registration to hold
                this id.

        Returns:
            `True` if a matching registration exists, `False` otherwise.
        """
        raise NotImplementedError

    async def start(self) -> None:  # noqa: B027  # optional hook; the default is a no-op
        """Prepare the backend before use. Does nothing by default."""

    async def stop(self) -> None:  # noqa: B027  # optional hook; the default is a no-op
        """Release the backend's resources. Does nothing by default."""


__all__ = ("ListenerCoordinator",)
