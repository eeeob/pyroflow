"""Redis-backed update coordinator shared across sessions."""

from __future__ import annotations as _annotations

import asyncio
import logging
from typing import Any, ClassVar, Literal, TYPE_CHECKING
from uuid import uuid4

from pytrove import cancel_task
from pytrove.enums import TimeUnit

from ..errors import UpdateAlreadyHandled
from ..utils import redis_token_lock
from .update_coordinator import UpdateCoordinator

if TYPE_CHECKING:
    from collections.abc import Sequence

    from pytrove.typings import Number
    from redis.asyncio import Redis
    from redis.asyncio.lock import Lock
    from redis.commands.core import AsyncScript

    from ..models import ListenerKey
    from ..typings import CoordinatedUpdateKeyT, CoordinatedUpdateIdT

log = logging.getLogger(__name__)

_SectionT = Literal["lock", "handled", "listen"]
"""Namespace of a Redis key: a lock, a handled mark or a listener registration."""


def _decode(value: bytes | str | None) -> str | None:
    """Return a Redis reply as text, keeping `None`.

    Example:
        >>> _decode(b"a"), _decode("b"), _decode(None)
        ('a', 'b', None)
    """
    return value.decode() if isinstance(value, bytes) else value


class RedisUpdateCoordinator(UpdateCoordinator):
    """Coordinator shared across sessions, backed by Redis.

    The lock is redis-py's distributed lock, a handled update is an expiring
    key whose existence is the state, and a listener registration is a key
    holding its owner id.

    Every session sharing the Redis shares the key names, which is what
    coordinates them. Each coordinator stamps its `fingerprint` into the value
    of every lock and registration it writes, so `start` picks a fingerprint
    no session uses and `stop` deletes what this coordinator still holds,
    leaving other sessions' keys and every handled key alone.

    A registration is a lease of `listener_ttl` seconds, which a background
    task renews every third of it while this session runs; a session that
    dies frees its registrations within one `listener_ttl`. The renewal also
    finds registrations a peer took over or cancelled, and reports each to
    `on_listener_lost`, so their waiters fail instead of waiting forever.

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
    LUA_REGISTER_LISTENER_SCRIPT: ClassVar[str] = """
    local previous = redis.call('GET', KEYS[1])
    if previous and ARGV[3] == '0' then
        return previous
    end
    redis.call('SET', KEYS[1], ARGV[1], 'PX', ARGV[2])
    return previous
    """
    """Lua script that sets the owner (`ARGV[1]`, expiring after `ARGV[2]` ms) unless the key is owned and `ARGV[3]` is `'0'`, returning the previous owner."""
    LUA_UNREGISTER_LISTENER_SCRIPT: ClassVar[str] = """
    if redis.call('GET', KEYS[1]) == ARGV[1] then
        redis.call('DEL', KEYS[1])
        return 1
    end
    return 0
    """
    """Lua script that deletes the key only if it holds the given owner, returning 1 if it did."""
    LUA_GETDEL_SCRIPT: ClassVar[str] = """
    local value = redis.call('GET', KEYS[1])
    if value then
        redis.call('DEL', KEYS[1])
    end
    return value
    """
    """Atomic `GET` + `DEL`, so a cancel names the owner it removed; `GETDEL` needs Redis 6.2+."""
    LUA_REFRESH_LISTENERS_SCRIPT: ClassVar[str] = """
    local lost = {}
    for i, key in ipairs(KEYS) do
        if redis.call('GET', key) == ARGV[i + 1] then
            redis.call('PEXPIRE', key, ARGV[1])
        else
            table.insert(lost, key)
        end
    end
    return lost
    """
    """Lua script that renews each key still holding its owner for `ARGV[1]` ms and returns the keys that lost it."""

    def __init__(
        self,
        redis: Redis,
        *args: Any,
        lock_ttl: Number = TimeUnit.HOUR,
        listener_ttl: Number = 60,
        sleep: Number = 0.1,
        **kw: Any,
    ) -> None:
        """Initialise the coordinator; other arguments go to `UpdateCoordinator`.

        Args:
            redis: The connected async Redis client holding the locks and the
                registries. The caller owns it and closes it after `stop`.
            *args: Positional arguments for `UpdateCoordinator`.
            lock_ttl: Seconds before a held lock expires on its own; a session
                that dies mid-handler keeps the lock until then.
            listener_ttl: Seconds a listener registration lives without being
                renewed; a dead session's registrations expire after it.
            sleep: Seconds between lock acquisition attempts while waiting.
            **kw: Keyword arguments for `UpdateCoordinator`.
        """
        super().__init__(*args, **kw)

        self.redis = redis
        """Async Redis client holding the locks and the registries."""
        self.lock_ttl = lock_ttl
        """Seconds before a held lock expires on its own."""
        self.listener_ttl = listener_ttl
        """Seconds a listener registration lives without being renewed."""
        self.sleep = sleep
        """Seconds between lock acquisition attempts while waiting."""
        self._sep = "|"
        """Separator joining the parts of a Redis key."""
        self._null = "_"
        """Placeholder for a missing `ListenerKey` component in a Redis key."""
        self._key_formats = {
            section: f"update{self._sep}{section}{self._sep}{self.update_type.__name__}{self._sep}{{key}}"
            for section in ("lock", "handled", "listen")
        }
        """Redis key template per section, with a `{key}` placeholder."""
        self._scripts: dict[str, AsyncScript] = {}
        """Registered Lua scripts by source, created on first use."""
        self._owned_listeners: dict[str, tuple[ListenerKey, str]] = {}
        """Registrations this session wrote, by Redis key, as `(key, owner_id)`; renewed by the heartbeat."""
        self._heartbeat: asyncio.Task | None = None
        """Task renewing `_owned_listeners`, set by `start`."""

    def build_key(
        self,
        key: CoordinatedUpdateKeyT | CoordinatedUpdateIdT,
        section: _SectionT = "lock",
    ) -> str:
        """Render `key` into its backend key under `section`.

        The section keeps a lock, a handled mark and a listener registration
        built from the same tuple apart.

        Args:
            key: The key tuple.
            section: The namespace, `"lock"`, `"handled"` or `"listen"`.

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

    def _listener_key(self, key: ListenerKey) -> str:
        """Render a listener key into its registration key, `_` standing in for a missing component.

        Example:
            >>> from pyroflow.models import ListenerKey
            >>> from pyroflow.types import Message
            >>> RedisUpdateCoordinator(None, Message)._listener_key(ListenerKey(1, None, 3))
            'update|listen|Message|1|_|3'
        """
        return self.build_key(
            tuple(self._null if value is None else value for value in key.to_tuple()), "listen"
        )

    def _script(self, source: str) -> AsyncScript:
        """Return the Lua script for `source`, registering it on first use."""
        script = self._scripts.get(source)

        if script is None:
            script = self._scripts[source] = self.redis.register_script(source)

        return script

    async def _fingerprinted_keys(self) -> list[bytes | str]:
        """Return every lock and listener key of this update type, whoever wrote it."""
        return [
            key
            for section in ("lock", "listen")
            async for key in self.redis.scan_iter(match=self.build_key(("*",), section=section))
        ]

    def lock(self, key: CoordinatedUpdateKeyT) -> Lock:
        """Build the distributed lock for `key`, expiring after `lock_ttl`.

        Its value is `<fingerprint>:<random>`: the fingerprint lets `stop` find
        it, and the random part keeps a lock that outlived `lock_ttl` from
        releasing a newer one on the same key.
        """
        # redis-py's `None` defaults let a dead session hold the lock and a waiter block forever.
        return redis_token_lock(
            self.redis,
            self.build_key(key, "lock"),
            token=f"{self.fingerprint}:{uuid4().hex}",
            timeout=self.lock_ttl,
            sleep=self.sleep,
            blocking_timeout=self.blocking_timeout,
            thread_local=False,
        )

    async def is_handled(self, key: CoordinatedUpdateIdT) -> bool:
        """Return whether the handled key for `key` exists in Redis."""
        return bool(await self.redis.exists(self.build_key(key, "handled")))

    async def mark_handled(self, key: CoordinatedUpdateIdT) -> None:
        """Set the handled key for `key` in Redis, expiring after `handled_ttl`, unless it exists.

        Raises:
            UpdateAlreadyHandled: If the handled key already exists.
        """
        # `px` rather than `ex`, so a sub-second `handled_ttl` is not truncated to zero.
        is_set = await self.redis.set(
            self.build_key(key, "handled"),
            1,
            px=int(self.handled_ttl * 1000),
            nx=True,
        )

        if not is_set:
            raise UpdateAlreadyHandled(key)

    async def register_listener(
        self, key: ListenerKey, owner_id: str, *, replace: bool
    ) -> str | None:
        """Claim `key` for `owner_id` for `listener_ttl` seconds; return the previous owner.

        A peer whose registration this replaces learns of it at its next renewal.
        """
        redis_key = self._listener_key(key)
        previous = _decode(
            await self._script(self.LUA_REGISTER_LISTENER_SCRIPT)(
                keys=[redis_key],
                args=[owner_id, int(self.listener_ttl * 1000), int(replace)],
                client=self.redis,
            )
        )

        if previous is None or replace:
            self._owned_listeners[redis_key] = (key, owner_id)

        return previous

    async def listener_owners(self, keys: Sequence[ListenerKey]) -> list[str | None]:
        """Return the owner id of each key with one `MGET`, `None` for a free one."""
        if not keys:
            return []

        values = await self.redis.mget([self._listener_key(key) for key in keys])

        return [_decode(value) for value in values]

    async def unregister_listener(self, key: ListenerKey, owner_id: str) -> bool:
        """Delete the registration of `key` only if `owner_id` still owns it."""
        redis_key = self._listener_key(key)

        if self._owned_listeners.get(redis_key) == (key, owner_id):
            del self._owned_listeners[redis_key]

        return bool(
            await self._script(self.LUA_UNREGISTER_LISTENER_SCRIPT)(
                keys=[redis_key], args=[owner_id], client=self.redis
            )
        )

    async def cancel_listener(self, key: ListenerKey) -> str | None:
        """Delete the registration of `key` whoever owns it; its owner learns of it at its next renewal."""
        redis_key = self._listener_key(key)
        self._owned_listeners.pop(redis_key, None)

        return _decode(
            await self._script(self.LUA_GETDEL_SCRIPT)(keys=[redis_key], client=self.redis)
        )

    async def refresh_listeners(self) -> None:
        """Renew this session's registrations and report each one a peer took to `on_listener_lost`."""
        owned = list(self._owned_listeners.items())

        if not owned:
            return

        lost = await self._script(self.LUA_REFRESH_LISTENERS_SCRIPT)(
            keys=[redis_key for redis_key, _ in owned],
            args=[int(self.listener_ttl * 1000), *(owner_id for _, (_, owner_id) in owned)],
            client=self.redis,
        )
        entries = dict(owned)

        for raw_key in lost:
            redis_key = raw_key.decode() if isinstance(raw_key, bytes) else raw_key
            entry = entries[redis_key]

            # A newer registration under the same key may have replaced the snapshot meanwhile.
            if self._owned_listeners.get(redis_key) == entry:
                del self._owned_listeners[redis_key]

            if self.on_listener_lost is not None:
                self.on_listener_lost(*entry)

    async def _renew_forever(self) -> None:
        """Run `refresh_listeners` every third of `listener_ttl`, logging failures."""
        while True:
            await asyncio.sleep(self.listener_ttl / 3)

            try:
                await self.refresh_listeners()
            except Exception:
                log.exception(
                    "Failed to renew %s listener registrations", self.update_type.__name__
                )

    async def start(self) -> None:
        """Pick a fingerprint no lock or registration in Redis carries yet, then start renewing registrations."""
        while True:
            keys = await self._fingerprinted_keys()
            values = await self.redis.mget(keys) if keys else []
            prefix = f"{self.fingerprint}:"

            if not any(
                (value.decode(errors="replace") if isinstance(value, bytes) else value).startswith(
                    prefix
                )
                for value in values
                if value is not None
            ):
                break

            self.fingerprint = uuid4().hex

        self._heartbeat = asyncio.create_task(self._renew_forever())

    async def stop(self) -> None:
        """Stop renewing, then delete the locks and registrations this coordinator holds; handled keys stay."""
        if self._heartbeat is not None:
            # `cancel_task` re-raises the caller's own cancellation instead of swallowing it.
            await cancel_task(self._heartbeat)
            self._heartbeat = None

        self._owned_listeners.clear()
        keys = await self._fingerprinted_keys()

        if keys:
            await self._script(self.LUA_DELETE_OWNED_SCRIPT)(
                keys=keys, args=[f"{self.fingerprint}:"], client=self.redis
            )


__all__ = ("RedisUpdateCoordinator",)
