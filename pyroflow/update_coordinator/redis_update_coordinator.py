from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from redis.asyncio import Redis

from ..utils.typings import Number
from .update_coordinator import UpdateCoordinator


class RedisUpdateCoordinator(UpdateCoordinator):
    """
    Cross-session coordinator backed by Redis.

    Both primitives map onto Redis directly, with no scripting needed: the
    lock is redis-py's own distributed lock, and the handled registry is a
    plain expiring key whose mere existence is the state.
    """

    def __init__(self, redis: 'Redis', *args, sleep: Number = 0.1, **kw) -> None:
        super().__init__(*args, **kw)

        self.redis = redis
        self.sleep = sleep

    def lock(self, key):
        """
        Build the distributed lock for ``key``.

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

    async def is_handled(self, key):
        return bool(
            await self.redis.exists(
                self.build_key(key, "handled")
            )
        )

    async def mark_handled(self, key):
        # px rather than ex so a sub-second handled_ttl survives the trip
        # instead of being truncated to zero.
        await self.redis.set(
            self.build_key(key, "handled"),
            1,
            px=int(self.handled_ttl * 1000),
        )
