"""Redis-backed listener coordinator shared by every session on the same Redis."""

from __future__ import annotations as _annotations

import asyncio
import logging
import uuid
from typing import ClassVar, Literal, TYPE_CHECKING

from pytrove import cancel_task, gather_helper

from ..models import ListenerKey
from .listener_coordinator import ListenerCoordinator

if TYPE_CHECKING:
    from pytrove.typings import Number
    from redis.asyncio import Redis
    from redis.asyncio.client import PubSub
    from redis.commands.core import AsyncScript

    from ..typings import AsyncLockProto, ListenerCoordinatorIdT, LockKeyT
    from ..update_listener import UpdateListener

log = logging.getLogger(__name__)


class RedisListenerCoordinator(ListenerCoordinator):
    """Listener coordinator that stores registrations in Redis.

    Registrations, locks and cancellations are visible to every session that
    shares the same Redis, and cancellations are broadcast to peers over
    pub/sub.
    """

    LUA_UNREGISTER_SCRIPT: ClassVar[str] = """
    local value = redis.call('GET', KEYS[1])

    if not value then
        return 1
    end

    if value == ARGV[1] then
        redis.call('DEL', KEYS[1])
        return 1
    end

    return 0
    """
    LUA_BULK_UNREGISTER_SCRIPT: ClassVar[str] = """
    local deleted_count = 0
    for i, key in ipairs(KEYS) do
        local expected_val = ARGV[i]
        local current_val = redis.call('GET', key)
        if current_val == expected_val then
            redis.call('DEL', key)
            deleted_count = deleted_count + 1
        end
    end
    return deleted_count
    """
    # Atomic `GET` + `DEL` so the cancel signal names the id actually removed,
    # not one a concurrent `register` put in between; `GETDEL` needs Redis 6.2+.
    LUA_GETDEL_SCRIPT: ClassVar[str] = """
    local value = redis.call('GET', KEYS[1])

    if value then
        redis.call('DEL', KEYS[1])
    end

    return value
    """

    lua_bulk_unregister: AsyncScript | None = None
    lua_unregister: AsyncScript | None = None
    lua_getdel: AsyncScript | None = None

    def __init__(
        self,
        redis: Redis,
        listener: UpdateListener,
        lock_timeout: Number = 30,
        lock_blocking_timeout: Number = 10,
    ) -> None:
        """Bind the coordinator to `redis` and register its Lua scripts.

        Args:
            redis: The async Redis client backing this coordinator.
            listener: The `UpdateListener` that owns it.
            lock_timeout: TTL in seconds of the per-chat lock, so a crashed
                holder does not keep the chat locked forever. Keep it above the
                longest critical section.
            lock_blocking_timeout: Seconds to wait for the lock before giving
                up with `LockError`. Keep it at or below `lock_timeout`.
        """
        super().__init__(listener)

        self.update_type_name = self.listener.__class__.__update_type__.__name__
        self.redis = redis

        self.lock_timeout = lock_timeout
        self.lock_blocking_timeout = lock_blocking_timeout

        self.pubsub: PubSub | None = None
        self.listening_task: asyncio.Task | None = None
        # Strong references keep in-flight cancels from being garbage collected;
        # `stop` drains them.
        self._pending_cancels: set[asyncio.Task] = set()

        self._sep = "|"
        self._key_format = (
            f"listen{self._sep}{{section}}{self._sep}{self.update_type_name}{self._sep}{{key}}"
        )
        self._null = "_"
        self._owned_registrations: dict[str, str] = {}

        self.cancel_channel_name = f"cancel{self._sep}listen{self._sep}{self.update_type_name}"

        self._register_scripts()

    def _register_scripts(self) -> None:
        """Register each Lua script with `self.redis` unless it is already set."""
        if self.lua_unregister is None:
            self.lua_unregister = self.redis.register_script(self.LUA_UNREGISTER_SCRIPT)
        if self.lua_bulk_unregister is None:
            self.lua_bulk_unregister = self.redis.register_script(self.LUA_BULK_UNREGISTER_SCRIPT)
        if self.lua_getdel is None:
            self.lua_getdel = self.redis.register_script(self.LUA_GETDEL_SCRIPT)

    def _unpack_key(self, packed_key: str) -> ListenerKey:
        """Rebuild the `ListenerKey` that `_pack_key` encoded."""
        chat_id, *rest = packed_key.split(self._sep)[3:]

        return ListenerKey(int(chat_id), *(None if key == self._null else int(key) for key in rest))

    def _pack_key(self, key: ListenerKey, section: Literal["registry", "lock"] = "registry") -> str:
        """Encode `key` as the Redis key of `section` for this update type.

        The result is `listen|<section>|<update type>|<chat_id>|<user_id>|<message_id>`,
        with `_` standing in for a missing component.
        """
        return self._key_format.format_map(
            {
                "section": section,
                "key": self._sep.join(
                    str(i if i is not None else self._null) for i in key.to_tuple
                ),
            }
        )

    def lock(self, key: LockKeyT) -> AsyncLockProto:
        """Build the Redis lock for `key` with `lock_timeout` and `lock_blocking_timeout`.

        Args:
            key: A chat id, a tuple of ids or a `ListenerKey`; ids are wrapped
                in a `ListenerKey` first.

        Returns:
            A Redis lock that is not thread-local.
        """
        if isinstance(key, int):
            key = ListenerKey(key)
        elif isinstance(key, tuple):
            key = ListenerKey(*key)

        # redis-py يجعل `timeout` و`blocking_timeout` افتراضياً `None`، أي قفل بلا TTL
        # يبقى بعد موت الـ session وانتظار بلا نهاية؛ لذلك نمرّرهما دائماً.
        return self.redis.lock(
            self._pack_key(key, "lock"),
            timeout=self.lock_timeout,
            blocking_timeout=self.lock_blocking_timeout,
            thread_local=False,
        )

    async def register(self, key: ListenerKey) -> str:
        """Claim `key` in Redis and return a fresh hex uuid as its id.

        Raises:
            KeyError: If `key` is already registered by any session.
        """
        packed_key = self._pack_key(key)
        coordinator_id = uuid.uuid4().hex

        success = await self.redis.set(packed_key, coordinator_id, nx=True)

        if not success:
            msg = f"Key {key!r} already registered"
            raise KeyError(msg)

        self._owned_registrations[packed_key] = coordinator_id

        return coordinator_id

    async def unregister(
        self, key: ListenerKey, coordinator_id: ListenerCoordinatorIdT | None = None
    ) -> bool:
        """Delete `key` from Redis, only if it still holds `coordinator_id` when given.

        Returns:
            `True` if `key` was deleted; with `coordinator_id`, also `True` when
            `key` was already gone.
        """
        packed_key = self._pack_key(key)

        if coordinator_id is None:
            self._owned_registrations.pop(packed_key, None)

            return bool(await self.redis.delete(packed_key))

        if self.lua_unregister is None:
            msg = "Lua unregister script is not registered"
            raise RuntimeError(msg)

        if cid := self._owned_registrations.pop(packed_key, None):
            if cid != coordinator_id:
                self._owned_registrations[packed_key] = cid

        return bool(
            await self.lua_unregister(keys=[packed_key], args=[coordinator_id], client=self.redis)
        )

    async def registered(
        self, key: ListenerKey, coordinator_id: ListenerCoordinatorIdT | None = None
    ) -> bool:
        """Return whether `key` exists in Redis, under `coordinator_id` when given."""
        value = await self.redis.get(self._pack_key(key))

        if value is None:
            return False

        if isinstance(value, bytes):
            value = value.decode()

        return coordinator_id is None or value == coordinator_id

    async def cancel(self, key: ListenerKey) -> bool:
        """Cancel the registration for `key` across every session.

        Deleting the key is what takes effect: no peer resolves an update with
        a listener it can no longer prove it owns. The removed id is then
        published so peers fail their waiters promptly; delivery is best-effort,
        so a peer may only notice at its own timeout.

        Returns:
            `True` if a registration existed and was removed, `False` otherwise.
        """
        if self.lua_getdel is None:
            msg = "Lua getdel script is not registered"
            raise RuntimeError(msg)

        packed_key = self._pack_key(key)

        self._owned_registrations.pop(packed_key, None)

        cancelled_id = await self.lua_getdel(keys=[packed_key], client=self.redis)

        if cancelled_id is None:
            # Nothing was registered, so no peer is waiting and no signal is sent.
            return False

        if isinstance(cancelled_id, bytes):
            cancelled_id = cancelled_id.decode()

        await self.redis.publish(
            self.cancel_channel_name,
            f"{packed_key}{self._sep}{cancelled_id}",
        )

        return True

    async def start(self) -> None:
        """Subscribe to the cancel channel and start listening for peer signals."""
        self.pubsub = self.redis.pubsub()

        await self.pubsub.subscribe(self.cancel_channel_name)

        self.listening_task = asyncio.create_task(self._listen_for_cancel_signals())

        log.info(
            "Subscribed to cancel channel %r and started _listen_for_cancel_signals task",
            self.cancel_channel_name,
        )

    async def stop(self) -> None:
        """Stop listening, close pub/sub and release this session's registrations.

        Waits for in-flight cancel signals first. A failure to delete the
        registrations is logged, not raised.
        """
        task = self.listening_task
        pubsub = self.pubsub

        if task is not None and not task.done():
            # `cancel_task` يعيد رفع إلغاء الـ caller نفسه بدل ابتلاعه
            await cancel_task(task)

            self.listening_task = None

            log.debug("Listening task stopped")

        if self._pending_cancels:
            # Abandoning dispatched cancels would leave local waiters hanging
            # until their own timeout.
            await gather_helper(*self._pending_cancels, return_exc=True)
            self._pending_cancels.clear()

        if pubsub is not None:
            await pubsub.unsubscribe()
            await pubsub.aclose()

            self.pubsub = None

            log.debug("PubSub unsubscribed and closed")

        if self._owned_registrations:
            keys, ids = zip(*self._owned_registrations.items(), strict=True)

            log.warning("RedisListenerCoordinator stopped with pending registrations: %s", keys)

            if self.lua_bulk_unregister is None:
                msg = "Lua bulk unregister script is not registered"
                raise RuntimeError(msg)

            keys, ids = list(keys), list(ids)

            try:
                deleted = await self.lua_bulk_unregister(keys=keys, args=ids, client=self.redis)
            except Exception:
                log.exception("Failed to bulk unregister keys during stop")
            else:
                log.info("Successfully bulk-deleted %d keys from Redis", deleted)
            finally:
                self._owned_registrations.clear()

    async def _apply_cancel_signal(self, key: ListenerKey, coordinator_id: str) -> None:
        """Cancel the local listener for `key` only if it holds `coordinator_id`; log failures."""
        try:
            await self.listener.cancel(
                key,
                cancel_coordinator=False,
                coordinator_id=coordinator_id,
            )
        except Exception:
            log.exception("Failed to apply cancel signal for %s", key)

    async def _listen_for_cancel_signals(self) -> None:
        """Read cancel signals from pub/sub and apply each one in its own task.

        Raises:
            RuntimeError: If `start` has not created the pub/sub yet.
        """
        if self.pubsub is None:
            msg = "PubSub has not been initialized. Call start() first."
            raise RuntimeError(msg)

        log.debug("Listening task started on channel %r", self.cancel_channel_name)

        async for msg in self.pubsub.listen():
            if msg["type"] != "message":
                continue

            data = msg["data"]

            if isinstance(data, bytes):
                data = data.decode()

            # Payload is `"<packed_key><sep><coordinator_id>"`. The id is a
            # hex uuid and never contains the separator, so taking it from
            # the right leaves the packed key intact.
            packed_key, _, coordinator_id = data.rpartition(self._sep)

            if not packed_key:
                log.warning("Malformed cancel signal payload: %r", data)
                continue

            key = self._unpack_key(packed_key)

            log.debug(
                "Received cancel signal for %s (token %r) from pubsub",
                key,
                coordinator_id,
            )

            # Applying a cancel waits for the chat lock; awaiting it inline would
            # stall every later signal behind this one.
            task = asyncio.create_task(self._apply_cancel_signal(key, coordinator_id))
            self._pending_cancels.add(task)
            task.add_done_callback(self._pending_cancels.discard)


__all__ = ("RedisListenerCoordinator",)
