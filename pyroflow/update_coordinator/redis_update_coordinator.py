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
    """Coordinator shared across sessions, backed by Redis.

    The lock is redis-py's distributed lock, and a handled update is an
    expiring key whose existence is the state.
    """

    def __init__(self, redis: Redis, *args: Any, sleep: Number = 0.1, **kw: Any) -> None:
        """Initialise the coordinator; other arguments go to `UpdateCoordinator`.

        Args:
            redis: The async Redis client holding the locks and the registry.
            *args: Positional arguments for `UpdateCoordinator`.
            sleep: Seconds between lock acquisition attempts while waiting.
            **kw: Keyword arguments for `UpdateCoordinator`.
        """
        super().__init__(*args, **kw)

        self.redis = redis
        """Async Redis client holding the locks and the handled registry."""
        self.sleep = sleep
        """Seconds between lock acquisition attempts while waiting."""

    def lock(self, key: UpdateCoordinatorKeyT) -> Lock:
        """Build the distributed lock for `key`, expiring after `lock_ttl`."""
        # redis-py's `None` defaults let a dead session hold the lock and a waiter block forever.
        return self.redis.lock(
            self.build_key(key, "lock"),
            timeout=self.lock_ttl,
            sleep=self.sleep,
            blocking_timeout=self.blocking_timeout,
            thread_local=False,
        )

    async def is_handled(self, key: UpdateCoordinatorKeyT) -> bool:
        """Return whether the handled key for `key` exists in Redis."""
        return bool(await self.redis.exists(self.build_key(key, "handled")))

    async def mark_handled(self, key: UpdateCoordinatorKeyT) -> None:
        """Set the handled key for `key` in Redis, expiring after `handled_ttl`."""
        # `px` rather than `ex`, so a sub-second `handled_ttl` is not truncated to zero.
        await self.redis.set(
            self.build_key(key, "handled"),
            1,
            px=int(self.handled_ttl * 1000),
        )


__all__ = ("RedisUpdateCoordinator",)
