from typing import Literal, Optional, Dict, Set, TYPE_CHECKING

if TYPE_CHECKING:
    from redis.asyncio.client import PubSub
    from redis.asyncio import Redis

from ..utils import gather_helper
from ..utils.typings import Number
from ..models import ListenerKey

from .listener_coordinator import ListenerCoordinator


import uuid
import logging
import asyncio


log = logging.getLogger(__name__)


 
 
class RedisListenerCoordinator(ListenerCoordinator):
    LUA_UNREGISTER_SCRIPT = """
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
    LUA_BULK_UNREGISTER_SCRIPT = """
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
    # Read and delete in one atomic step so the caller learns exactly which
    # registration it invalidated. A separate GET then DEL could report an id
    # that a concurrent register() had already replaced, and the cancel signal
    # would then name the wrong generation. GETDEL would do, but needs Redis
    # 6.2+; this works everywhere and matches the scripts above.
    LUA_GETDEL_SCRIPT = """
    local value = redis.call('GET', KEYS[1])

    if value then
        redis.call('DEL', KEYS[1])
    end

    return value
    """

    lua_bulk_unregister = None
    lua_unregister = None
    lua_getdel = None


    def __init__(
        self,
        redis: 'Redis',
        listener,
        lock_timeout: Number = 30,
        lock_blocking_timeout: Number = 10,
    ):
        """
        Parameters:
            redis:    The async Redis client backing this coordinator.
            listener: The :class:`UpdateListener` that owns it.

            lock_timeout:
                TTL (seconds) of the per-chat lock. Both values are always
                applied when the lock is built — redis-py defaults them to
                ``None``, which is unusable here: a lock with no TTL survives
                the session that took it, so a process that dies mid-critical
                section leaves that chat locked in Redis permanently, and every
                other session then blocks on it forever with no way to recover.

                Size it above the longest critical section (all of them are
                short Redis round-trips) but low enough that a crashed holder
                is reclaimed quickly.

            lock_blocking_timeout:
                How long (seconds) to wait for the lock before giving up with
                ``LockError``. Without it a waiter blocks forever; failing
                loudly is recoverable, hanging silently is not. Keep it at or
                below ``lock_timeout`` so a waiter never outlasts the TTL it
                is waiting on.
        """
        super().__init__(listener)

        self.update_type_name = self.listener.__class__.__update_type__.__name__
        self.redis = redis

        self.lock_timeout = lock_timeout
        self.lock_blocking_timeout = lock_blocking_timeout

        self.pubsub: Optional['PubSub'] = None
        self.listening_task: Optional[asyncio.Task] = None
        # In-flight cancel applications. Held strongly so they are not garbage
        # collected mid-flight, and drained on stop() so shutdown does not
        # abandon a cancellation halfway through.
        self._pending_cancels: Set[asyncio.Task] = set()

        self._sep = "|"
        self._key_format = (
            f"listen{self._sep}{{section}}{self._sep}"
            f"{self.update_type_name}{self._sep}{{key}}"
        )
        self._null = "_"
        self._owned_registrations: Dict[str, str] = {}

        self.cancel_channel_name = f"cancel{self._sep}listen{self._sep}{self.update_type_name}"
        
        self._register_scripts()
    
    def _register_scripts(self):
        if self.lua_unregister is None:
            self.lua_unregister = self.redis.register_script(self.LUA_UNREGISTER_SCRIPT)
        if self.lua_bulk_unregister is None:
            self.lua_bulk_unregister = self.redis.register_script(self.LUA_BULK_UNREGISTER_SCRIPT)
        if self.lua_getdel is None:
            self.lua_getdel = self.redis.register_script(self.LUA_GETDEL_SCRIPT)

    def _unpack_key(self, packed_key: str) -> ListenerKey:
        keys = [
            None if key == self._null else int(key)
            for key in packed_key.split(self._sep)[3:]
        ]

        return ListenerKey(*keys)

    def _pack_key(self, key: ListenerKey, section: Literal["registry", "lock"] = "registry") -> str:
        return self._key_format.format_map(
            {
                "section": section, 
                "key": self._sep.join(str(i if i is not None else self._null) for i in key.to_tuple)
            }
        )


    def lock(self, key):
        """
        Build the per-chat lock.

        ``timeout`` and ``blocking_timeout`` are always passed: leaving either
        at redis-py's ``None`` default turns a crashed or contended session
        into a permanent, unrecoverable stall (see :meth:`__init__`).
        """
        if isinstance(key, int):
            key = ListenerKey(key)
        elif isinstance(key, tuple):
            key = ListenerKey(*key)

        return self.redis.lock(
            self._pack_key(key, "lock"),
            timeout=self.lock_timeout,
            blocking_timeout=self.lock_blocking_timeout,
            thread_local=False,
            )
    

    async def register(self, key):
        packed_key = self._pack_key(key)
        coordinator_id = uuid.uuid4().hex

        success = await self.redis.set(
            packed_key, 
            coordinator_id, 
            nx=True 
        )

        if not success:
            raise KeyError(
                f"Key {key!r} already registered"
            )
        
        self._owned_registrations[packed_key] = coordinator_id

        return coordinator_id

    async def unregister(self, key, coordinator_id = None):
        packed_key = self._pack_key(key)

        if coordinator_id is None:
            self._owned_registrations.pop(packed_key, None)

            return bool(
                await self.redis.delete(packed_key)
            )
        
        if self.lua_unregister is None:
            raise RuntimeError("Lua unregister script is not registered")
        
        if cid := self._owned_registrations.pop(packed_key, None):
            if cid != coordinator_id:
                self._owned_registrations[packed_key] = cid

        return bool(
            await self.lua_unregister(
                keys=[packed_key], 
                args=[coordinator_id], 
                client=self.redis
            )
        )

    async def registered(self, key, coordinator_id = None) -> bool:
        value = await self.redis.get(
            self._pack_key(key)
        )

        if value is None:
            return False

        if isinstance(value, bytes):
            value = value.decode()

        return (
            coordinator_id is None
            or value == coordinator_id
        )

    async def cancel(self, key) -> bool:
        """
        Cancel the registration for ``key`` across every session.

        Deletion happens first and is what actually makes the cancellation
        take effect: once the key is gone, no peer can prove ownership of it,
        so no peer will resolve an update with the listener it held. The
        published signal is only an optimisation — it lets peers fail their
        waiters promptly instead of sitting until timeout. Correctness
        therefore does not depend on pub/sub delivery, which is best-effort
        and can be delayed or dropped entirely.

        The signal carries the id that was actually invalidated, so a peer
        can tell whether the listener it currently holds is the one being
        cancelled or a newer one that reused the same key.

        Returns:
            ``True`` if a registration existed and was removed.
        """

        packed_key = self._pack_key(key)

        self._owned_registrations.pop(packed_key, None)

        cancelled_id = await self.lua_getdel(keys=[packed_key], client=self.redis)

        if cancelled_id is None:
            # Nothing was registered — no peer is waiting, so no signal.
            return False

        if isinstance(cancelled_id, bytes):
            cancelled_id = cancelled_id.decode()

        await self.redis.publish(
            self.cancel_channel_name,
            f"{packed_key}{self._sep}{cancelled_id}",
        )

        return True

    async def start(self):
        self.pubsub = self.redis.pubsub()

        await self.pubsub.subscribe(
            self.cancel_channel_name
        )

        self.listening_task = asyncio.create_task(
            self._listen_for_cancel_signals()
        )

        log.info(
            "Subscribed to cancel channel %r and started _listen_for_cancel_signals task",
            self.cancel_channel_name
        )

    async def stop(self):
        task = self.listening_task
        pubsub = self.pubsub

        if task is not None and not task.done():
            task.cancel()

            try:
                await task
            except asyncio.CancelledError:
                pass

            self.listening_task = None

            log.debug("Listening task stopped")

        if self._pending_cancels:
            # Let already-dispatched cancels finish; abandoning them would
            # leave local waiters hanging until their own timeout.
            await gather_helper(*self._pending_cancels, return_exc=True)
            self._pending_cancels.clear()

        if pubsub is not None:
            await pubsub.unsubscribe()
            await pubsub.aclose()

            self.pubsub = None

            log.debug("PubSub unsubscribed and closed")
        
        if self._owned_registrations:
            keys, ids = zip(*self._owned_registrations.items())
            
            log.warning("RedisListenerCoordinator stopped with pending registrations: %s", keys)

            if self.lua_bulk_unregister is None:
                raise RuntimeError("Lua bulk unregister script is not registered")

            keys, ids = list(keys), list(ids)

            try:
                deleted = await self.lua_bulk_unregister(
                    keys=keys,
                    args=ids,
                    client=self.redis
                )
            except Exception:
                log.exception("Failed to bulk unregister keys during stop")
            else:
                log.info("Successfully bulk-deleted %d keys from Redis", deleted)
            finally:
                self._owned_registrations.clear()
                

    async def _apply_cancel_signal(self, key: ListenerKey, coordinator_id: str) -> None:
        """Apply one cancel signal, guarding the generation it targets."""
        try:
            await self.listener.cancel(
                key,
                cancel_coordinator=False,
                coordinator_id=coordinator_id,
            )
        except Exception:
            log.exception("Failed to apply cancel signal for %s", key)

    async def _listen_for_cancel_signals(self) -> None:
        if self.pubsub is None:
            raise RuntimeError("PubSub has not been initialized. Call start() first.")

        log.debug(
            "Listening task started on channel %r",
            self.cancel_channel_name
        )

        try:
            async for msg in self.pubsub.listen():
                if msg["type"] != "message":
                    continue

                data = msg["data"]

                if isinstance(data, bytes):
                    data = data.decode()

                # Payload is "<packed_key><sep><coordinator_id>". The id is a
                # hex uuid and never contains the separator, so taking it from
                # the right leaves the packed key intact.
                packed_key, _, coordinator_id = data.rpartition(self._sep)

                if not packed_key:
                    log.warning("Malformed cancel signal payload: %r", data)
                    continue

                key = self._unpack_key(packed_key)

                log.debug(
                    "Received cancel signal for %s (token %r) from pubsub",
                    key, coordinator_id,
                )

                # Applying a cancel takes the chat lock, which may be held
                # elsewhere. Awaiting it inline would stall every later signal
                # behind this one — head-of-line blocking that grows the very
                # cancellation delay this channel exists to avoid. Dispatch it
                # and keep reading.
                task = asyncio.create_task(
                    self._apply_cancel_signal(key, coordinator_id)
                )
                self._pending_cancels.add(task)
                task.add_done_callback(self._pending_cancels.discard)

        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("Listening task crashed — cancel signals will no longer be received")
            raise





