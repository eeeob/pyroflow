"""Redis-backed update coordinator shared across sessions."""

from __future__ import annotations as _annotations

from typing import Any, Literal, TYPE_CHECKING

from pytrove.enums import TimeUnit

from .update_coordinator import UpdateCoordinator

if TYPE_CHECKING:
    from pytrove.typings import Number
    from redis.asyncio import Redis
    from redis.asyncio.lock import Lock

    from ..typings import CoordinatedUpdateKeyT, CoordinatedUpdateIdT


class RedisUpdateCoordinator(UpdateCoordinator):
    """Coordinator shared across sessions, backed by Redis.

    The lock is redis-py's distributed lock, and a handled update is an
    expiring key whose existence is the state.
    """

    def __init__(
        self,
        redis: Redis,
        *args: Any,
        lock_ttl: Number = TimeUnit.HOUR,
        sleep: Number = 0.1,
        **kw: Any,
    ) -> None:
        """Initialise the coordinator; other arguments go to `UpdateCoordinator`.

        Args:
            redis: The async Redis client holding the locks and the registry.
            *args: Positional arguments for `UpdateCoordinator`.
            lock_ttl: Seconds before a held lock expires on its own; a session
                that dies mid-handler keeps the lock until then.
            sleep: Seconds between lock acquisition attempts while waiting.
            **kw: Keyword arguments for `UpdateCoordinator`.
        """
        super().__init__(*args, **kw)

        self.redis = redis
        """Async Redis client holding the locks and the handled registry."""
        self.lock_ttl = lock_ttl
        """Seconds before a held lock expires on its own."""
        self.sleep = sleep
        """Seconds between lock acquisition attempts while waiting."""
        self._sep = "|"
        """Separator joining the parts of a Redis key."""
        self._key_formats = {
            section: f"update{self._sep}{section}{self._sep}{self.update_type.__name__}{self._sep}{{key}}"
            for section in ("lock", "handled")
        }
        """Redis key template per section, with a `{key}` placeholder."""

    def build_key(
        self,
        key: CoordinatedUpdateKeyT | CoordinatedUpdateIdT,
        section: Literal["lock", "handled"] = "lock",
    ) -> str:
        """Render `key` into its backend key under `section`.

        The section keeps a lock and a handled mark built from the same tuple
        apart.

        Args:
            key: The key tuple.
            section: The namespace, `"lock"` or `"handled"`.

        Returns:
            The backend key.

        Example:
            >>> from pyroflow.types import Message
            >>> coordinator = RedisUpdateCoordinator(None, Message)  # build_key never touches Redis
            >>> coordinator.build_key((-100123, 42))
            'update|lock|Message|-100123|42'
            >>> coordinator.build_key((-100123, 42), "handled")
            'update|handled|Message|-100123|42'
        """
        return self._key_formats[section].format_map({"key": self._sep.join(str(i) for i in key)})

    def lock(self, key: CoordinatedUpdateKeyT) -> Lock:
        """Build the distributed lock for `key`, expiring after `lock_ttl`."""
        # redis-py's `None` defaults let a dead session hold the lock and a waiter block forever.
        return self.redis.lock(
            self.build_key(key, "lock"),
            timeout=self.lock_ttl,
            sleep=self.sleep,
            blocking_timeout=self.blocking_timeout,
            thread_local=False,
        )

    async def is_handled(self, key: CoordinatedUpdateIdT) -> bool:
        """Return whether the handled key for `key` exists in Redis."""
        return bool(await self.redis.exists(self.build_key(key, "handled")))

    async def mark_handled(self, key: CoordinatedUpdateIdT) -> None:
        """Set the handled key for `key` in Redis, expiring after `handled_ttl`."""
        # `px` rather than `ex`, so a sub-second `handled_ttl` is not truncated to zero.
        await self.redis.set(
            self.build_key(key, "handled"),
            1,
            px=int(self.handled_ttl * 1000),
        )


__all__ = ("RedisUpdateCoordinator",)
