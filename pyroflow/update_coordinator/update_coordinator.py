"""Abstract base class for update coordinator backends."""

from __future__ import annotations as _annotations

from abc import ABC, abstractmethod
from typing import Any, TYPE_CHECKING

from pytrove.enums import TimeUnit

if TYPE_CHECKING:
    from pytrove.typings import Number

    from ..typings import AsyncLockProto, UpdateType, CoordinatedUpdateKeyT, CoordinatedUpdateIdT


class UpdateCoordinator(ABC):
    """Abstract backend that locks update scopes and remembers handled updates.

    It holds two independent primitives. `lock` is a plain mutex over the
    scope the caller chose, and keeps no state once released. `is_handled` and
    `mark_handled` form the handled registry: a set of update ids, each either
    handled (skip it) or not. Each backend keeps the two apart, so the same key
    tuple can serve both.

    Args:
        update_type: The Pyrogram update class handled; its name namespaces
            the keys.
        lock_ttl: Seconds before a held distributed lock expires on its own;
            a session that dies mid-handler keeps the lock until then. Only
            `RedisUpdateCoordinator` applies it.
        handled_ttl: Seconds an update id stays registered as handled, which
            is the deduplication window.
        blocking_timeout: Maximum seconds `lock` waits before reporting
            failure. Keep it small: the dispatcher waits while holding its
            worker lock, so a contended update stalls that worker meanwhile.
        **kw: Passed to the next class in the MRO.
    """

    def __init__(
        self,
        update_type: type[UpdateType],
        lock_ttl: Number = TimeUnit.HOUR,
        handled_ttl: Number = TimeUnit.HOUR,
        blocking_timeout: Number = 5,
        **kw: Any,
    ) -> None:
        """Initialise the coordinator; see the class docstring for the parameters."""
        self.lock_ttl = lock_ttl
        """Seconds before a held distributed lock expires on its own."""
        self.handled_ttl = handled_ttl
        """Seconds an update id stays registered as handled."""
        self.blocking_timeout = blocking_timeout
        """Maximum seconds `lock` waits before reporting failure."""

        self._update_name = update_type.__name__
        """Name of the handled update class, for backends that namespace their keys with it."""

        super().__init__(**kw)

    @abstractmethod
    def lock(self, key: CoordinatedUpdateKeyT) -> AsyncLockProto:
        """Return the mutex for the scope `key`.

        Implementations honour `blocking_timeout`: `acquire()` returns `False`
        instead of waiting forever, and `async with` raises instead of entering
        unlocked. Distributed backends must also expire the lock after
        `lock_ttl`; the in-process `TimedLock` never expires.

        Args:
            key: The scope to serialise, such as a chat or a single update.

        Returns:
            An async lock usable with `async with`.
        """
        raise NotImplementedError

    @abstractmethod
    async def is_handled(self, key: CoordinatedUpdateIdT) -> bool:
        """Return whether `key` is registered as handled.

        Args:
            key: The update's identity, not its lock scope.

        Returns:
            `True` if the update was already processed and should be skipped.
        """
        raise NotImplementedError

    @abstractmethod
    async def mark_handled(self, key: CoordinatedUpdateIdT) -> None:
        """Register `key` as handled for `handled_ttl` seconds.

        Marking a key again only refreshes its expiry.

        Args:
            key: The update's identity, not its lock scope.
        """
        raise NotImplementedError

    async def start(self) -> None:  # noqa: B027  # optional lifecycle hook; subclasses override only when needed
        """Prepare the backend before use. Does nothing by default."""

    async def stop(self) -> None:  # noqa: B027  # optional lifecycle hook; subclasses override only when needed
        """Release the backend's resources. Does nothing by default."""


__all__ = ("UpdateCoordinator",)
