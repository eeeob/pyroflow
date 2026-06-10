from typing import Literal, Optional, Dict, TYPE_CHECKING

if TYPE_CHECKING:
    from redis.asyncio.client import PubSub
    from redis.asyncio import Redis

from ..utils import gather_helper
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

    lua_bulk_unregister = None
    lua_unregister = None


    def __init__(self, redis: 'Redis', listener):
        super().__init__(listener)

        self.update_type_name = self.listener.__class__.__update_type__.__name__
        self.redis = redis

        self.pubsub: Optional['PubSub'] = None
        self.listening_task: Optional[asyncio.Task] = None

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
        if isinstance(key, int):
            key = ListenerKey(key)
        elif isinstance(key, tuple):
            key = ListenerKey(*key)

        return self.redis.lock(
            self._pack_key(key, "lock"), 
            thread_local=False
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

    async def cancel(self, key):
        await gather_helper(
            self.redis.publish(
                self.cancel_channel_name,
                self._pack_key(key)
            ), 
            self.unregister(key), 
        )

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

                key = self._unpack_key(data)

                log.debug(
                    "Received cancel signal for %s from pubsub", key
                )

                await self.listener.cancel(
                    key, cancel_coordinator=False
                )

        except Exception:
            log.exception("Listening task crashed — cancel signals will no longer be received")
            raise





