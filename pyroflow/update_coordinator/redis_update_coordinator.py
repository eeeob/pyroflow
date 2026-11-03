"""Redis-backed update coordinator shared across sessions."""

from __future__ import annotations as _annotations

from functools import partial
from typing import Any, ClassVar, Literal, TYPE_CHECKING
from uuid import uuid4

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

    Every session sharing the Redis shares the key names, which is what
    coordinates them. Each coordinator stamps its `fingerprint` into the value
    of every lock it takes, so `stop` deletes the locks it still holds and
    leaves other sessions' locks and every handled key alone.

    Pass a connected client. The coordinator never opens or closes it: close
    it yourself after the coordinator stops.
    """

    LUA_DELETE_OWNED_SCRIPT: ClassVar[str] = """
    local deleted_count = 0
    for _, key in ipairs(KEYS) do
        local value = redis.call('GET', key)
        if value and string.sub(value, 1, #ARGV[1]) == ARGV[1] then
            redis.call('DEL', key)
            deleted_count = deleted_count + 1
        end
    end
    return deleted_count
    """
    """Lua script that deletes each key whose value starts with the given prefix and returns the count."""

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
            redis: The connected async Redis client holding the locks and the
                registry. The caller owns it and closes it after `stop`.
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
        self.fingerprint = uuid4().hex
        """Prefix of every lock value this coordinator writes, unique among the sessions."""
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

    async def _lock_keys(self) -> list[bytes | str]:
        """Return every lock key of this update type, whoever holds it."""
        pattern = self._key_formats["lock"].format_map({"key": "*"})
        return [key async for key in self.redis.scan_iter(match=pattern)]

    def lock(self, key: CoordinatedUpdateKeyT) -> Lock:
        """Build the distributed lock for `key`, expiring after `lock_ttl`.

        Its value is `<fingerprint>:<random>`: the fingerprint lets `stop` find
        it, and the random part keeps a lock that outlived `lock_ttl` from
        releasing a newer one on the same key.
        """
        # redis-py's `None` defaults let a dead session hold the lock and a waiter block forever.
        lock = self.redis.lock(
            self.build_key(key, "lock"),
            timeout=self.lock_ttl,
            sleep=self.sleep,
            blocking_timeout=self.blocking_timeout,
            thread_local=False,
        )
        # `acquire(token=...)` is redis-py's only hook for the value; `async with` calls `acquire()` too.
        lock.acquire = partial(lock.acquire, token=f"{self.fingerprint}:{uuid4().hex}")  # ty: ignore[invalid-assignment]  # the partial only binds `token`, which callers never pass
        return lock

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

    async def start(self) -> None:
        """Pick a fingerprint no lock in Redis carries yet."""
        while True:
            keys = await self._lock_keys()
            values = await self.redis.mget(keys) if keys else []
            prefix = f"{self.fingerprint}:"

            if not any(
                (value.decode(errors="replace") if isinstance(value, bytes) else value).startswith(
                    prefix
                )
                for value in values
                if value is not None
            ):
                return

            self.fingerprint = uuid4().hex

    async def stop(self) -> None:
        """Delete the locks this coordinator still holds; handled keys stay for the other sessions."""
        keys = await self._lock_keys()

        if keys:
            delete_owned = self.redis.register_script(self.LUA_DELETE_OWNED_SCRIPT)
            await delete_owned(keys=keys, args=[f"{self.fingerprint}:"])


__all__ = ("RedisUpdateCoordinator",)
