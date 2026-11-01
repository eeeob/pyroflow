"""Redis-backed update coordinator shared across sessions."""

from __future__ import annotations as _annotations

from typing import Any, TYPE_CHECKING

from .update_coordinator import UpdateCoordinator

if TYPE_CHECKING:
    from pytrove.typings import Number
    from redis.asyncio import Redis
    from redis.asyncio.lock import Lock

    from ..typings import UpdateCoordinatorKeyT


class RedisUpdateCoordinator(UpdateCoordinator):
    """Cross-session coordinator backed by Redis.

    Both primitives map onto Redis directly, with no scripting needed: the
    lock is redis-py's own distributed lock, and the handled registry is a
    plain expiring key whose mere existence is the state.
    """

    def __init__(self, redis: Redis, *args: Any, sleep: Number = 0.1, **kw: Any) -> None:
        """Initialise the coordinator; other arguments go to :class:`UpdateCoordinator`.

        Args:
            redis: The async Redis client holding the locks and the registry.
            *args: Positional arguments for :class:`UpdateCoordinator`.
            sleep: Seconds between lock acquisition attempts while waiting.
            **kw: Keyword arguments for :class:`UpdateCoordinator`.
        """
        super().__init__(*args, **kw)

        self.redis = redis
        self.sleep = sleep

    def lock(self, key: UpdateCoordinatorKeyT) -> Lock:
        """Build the distributed lock for ``key``.

        ``timeout`` and ``blocking_timeout`` are always passed: leaving
        either at redis-py's ``None`` default turns a crashed or contended
        session into a permanent, unrecoverable stall — a lock with no TTL
        outlives the session that took it, and a waiter with no timeout
        blocks on it forever.
        """
        return self.redis.lock(
            self.build_key(key, "lock"),
            timeout=self.lock_ttl,
            sleep=self.sleep,
            blocking_timeout=self.blocking_timeout,
            thread_local=False,
        )

    async def is_handled(self, key: UpdateCoordinatorKeyT) -> bool:
        """Whether the handled key for ``key`` exists in Redis."""
        return bool(await self.redis.exists(self.build_key(key, "handled")))

    async def mark_handled(self, key: UpdateCoordinatorKeyT) -> None:
        """Set the handled key for ``key`` in Redis, expiring after ``handled_ttl``."""
        # `px` rather than `ex` so a sub-second `handled_ttl` survives the trip
        # instead of being truncated to zero.
        await self.redis.set(
            self.build_key(key, "handled"),
            1,
            px=int(self.handled_ttl * 1000),
        )


__all__ = ("RedisUpdateCoordinator",)
