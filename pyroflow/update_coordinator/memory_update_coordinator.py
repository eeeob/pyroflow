"""In-memory update coordinator for a single process."""

from __future__ import annotations as _annotations
from typing import TYPE_CHECKING, Any
from functools import partial
from cachetools import TTLCache

from ..utils import AsyncioLock
from pytrove import DefaultWeakValueDict

from .update_coordinator import UpdateCoordinator

if TYPE_CHECKING:
    from pytrove.typings import Number

    from ..typings import UpdateCoordinatorKeyT

import asyncio


class TimedLock(AsyncioLock):
    """An :class:`asyncio.Lock` with a bounded wait.

    A bare ``asyncio.Lock`` waits forever, which is unusable here: the
    dispatcher waits on this while holding its worker lock, so one stuck
    holder would stall that worker permanently with no way to recover.

    ``acquire()`` returns ``False`` on timeout rather than raising, matching
    redis-py's ``Lock`` so both backends behave identically. ``async with``
    still raises, since proceeding *unlocked* into a critical section is
    never what the caller meant.
    """

    def __init__(self, blocking_timeout: Number) -> None:
        """Create an unlocked lock that waits at most ``blocking_timeout`` seconds."""
        super().__init__()

        self.blocking_timeout = blocking_timeout

    async def acquire(self) -> bool:  # ty: ignore[invalid-method-override]  # asyncio.Lock.acquire is typed Literal[True]; the bounded wait returns False on timeout
        """Acquire the lock, waiting at most ``blocking_timeout`` seconds.

        Returns:
            ``True`` once the lock is held, ``False`` if the wait timed out.
        """
        try:
            return await asyncio.wait_for(super().acquire(), self.blocking_timeout)
        except asyncio.TimeoutError:
            return False

    async def __aenter__(self) -> None:
        """Acquire the lock for an ``async with`` block.

        Raises:
            TimeoutError: If the lock is not acquired within ``blocking_timeout``.
        """
        if not await self.acquire():
            msg = f"Timeout waiting for lock after {self.blocking_timeout}s"
            raise TimeoutError(msg)


class MemoryUpdateCoordinator(UpdateCoordinator):
    """Single-process coordinator, backed by plain in-memory structures.

    The default when no factory is supplied. Coordination is real but local:
    it serialises this process's own workers and remembers what this process
    has handled. Use the Redis backend to coordinate across sessions.

    Parameters:
        max_handled: How many handled ids to retain. Together with
                     ``handled_ttl`` this bounds the registry, which is
                     otherwise append-only and would grow for the lifetime
                     of the process.
    """

    def __init__(self, *args: Any, max_handled: int = 1000, **kw: Any) -> None:
        """Initialise the coordinator; other arguments go to :class:`UpdateCoordinator`."""
        super().__init__(*args, **kw)

        # Weakly held: a lock exists only while somebody is holding or
        # waiting on it, so idle scopes cost nothing. Callers keep a strong
        # reference for as long as they use it, which is what keeps the
        # entry alive across an acquire/release pair.
        self.locks = DefaultWeakValueDict(partial(TimedLock, self.blocking_timeout))

        self.handled: TTLCache[str, None] = TTLCache(maxsize=max_handled, ttl=self.handled_ttl)

    def lock(self, key: UpdateCoordinatorKeyT) -> TimedLock:
        """Return the process-local :class:`TimedLock` for ``key``."""
        return self.locks[self.build_key(key, "lock")]

    async def is_handled(self, key: UpdateCoordinatorKeyT) -> bool:
        """Whether ``key`` is in the in-memory handled registry."""
        return self.build_key(key, "handled") in self.handled

    async def mark_handled(self, key: UpdateCoordinatorKeyT) -> None:
        """Add ``key`` to the in-memory handled registry."""
        self.handled[self.build_key(key, "handled")] = None

    async def stop(self) -> None:
        """Clear the handled registry."""
        self.handled.clear()


__all__ = ("MemoryUpdateCoordinator",)
