"""In-memory update coordinator for a single process."""

from __future__ import annotations as _annotations

import asyncio
from functools import partial
from typing import Any, TYPE_CHECKING

from cachetools import TTLCache
from pytrove import DefaultWeakValueDict

from ..utils import AsyncioLock
from .update_coordinator import UpdateCoordinator

if TYPE_CHECKING:
    from pytrove.typings import Number

    from ..typings import CoordinatedUpdateKeyT, CoordinatedUpdateIdT


class TimedLock(AsyncioLock):
    """An `asyncio.Lock` whose wait is bounded by `blocking_timeout`.

    `acquire()` returns `False` on timeout, like redis-py's `Lock`, while
    `async with` raises.

    Example:
        >>> async def main():
        ...     lock = TimedLock(blocking_timeout=0.01)
        ...     first = await lock.acquire()
        ...     return first, await lock.acquire()
        >>> asyncio.run(main())
        (True, False)
    """

    def __init__(self, blocking_timeout: Number) -> None:
        """Create an unlocked lock that waits at most `blocking_timeout` seconds."""
        super().__init__()

        self.blocking_timeout = blocking_timeout
        """Maximum seconds `acquire` waits for the lock."""

    async def acquire(self) -> bool:  # ty: ignore[invalid-method-override]  # `asyncio.Lock.acquire` is typed `Literal[True]`; the bounded wait returns `False` on timeout
        """Acquire the lock, waiting at most `blocking_timeout` seconds.

        Returns:
            `True` once the lock is held, `False` if the wait timed out.
        """
        # A bare `asyncio.Lock` waits forever while the dispatcher holds its worker lock.
        try:
            return await asyncio.wait_for(super().acquire(), self.blocking_timeout)
        except asyncio.TimeoutError:
            return False

    async def __aenter__(self) -> None:
        """Acquire the lock for an `async with` block.

        Raises:
            TimeoutError: If the lock is not acquired within `blocking_timeout`.
        """
        if not await self.acquire():
            msg = f"Timeout waiting for lock after {self.blocking_timeout}s"
            raise TimeoutError(msg)


class MemoryUpdateCoordinator(UpdateCoordinator):
    """Process-local coordinator backed by in-memory structures.

    The default backend. It serialises this process's workers and remembers
    what this process handled; use `RedisUpdateCoordinator` to coordinate
    across sessions.

    Args:
        max_handled: The most handled ids kept; with `handled_ttl` it bounds
            the registry.

    Example:
        >>> from pyroflow.types import Message
        >>> async def main():
        ...     coordinator = MemoryUpdateCoordinator(Message)
        ...     before = await coordinator.is_handled((1, 2))
        ...     await coordinator.mark_handled((1, 2))
        ...     return before, await coordinator.is_handled((1, 2))
        >>> asyncio.run(main())
        (False, True)
    """

    def __init__(self, *args: Any, max_handled: int = 1000, **kw: Any) -> None:
        """Initialise the coordinator; other arguments go to `UpdateCoordinator`."""
        super().__init__(*args, **kw)

        self.locks = DefaultWeakValueDict(partial(TimedLock, self.blocking_timeout))
        """Lock per scope key, held weakly: an idle scope's lock is dropped, so callers keep a reference across `acquire`/`release`."""

        self.handled: TTLCache[CoordinatedUpdateIdT, None] = TTLCache(
            maxsize=max_handled, ttl=self.handled_ttl
        )
        """Expiring registry of handled update keys."""

    def lock(self, key: CoordinatedUpdateKeyT) -> TimedLock:
        """Return the process-local `TimedLock` for `key`.

        The same lock is returned only while someone references it, so keep
        it between `acquire` and `release`.
        """
        return self.locks[key]

    async def is_handled(self, key: CoordinatedUpdateIdT) -> bool:
        """Return whether `key` is in the in-memory handled registry."""
        return key in self.handled

    async def mark_handled(self, key: CoordinatedUpdateIdT) -> None:
        """Add `key` to the in-memory handled registry."""
        self.handled[key] = None

    async def stop(self) -> None:
        """Clear the handled registry."""
        self.handled.clear()


__all__ = ("MemoryUpdateCoordinator",)
