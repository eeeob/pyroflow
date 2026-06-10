from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from redis.asyncio import Redis

from ..enums import UpdateLockState
from .update_coordinator import UpdateCoordinator

class RedisUpdateCoordinator(UpdateCoordinator):
    LUA_ACQUIRE_SCRIPT = f"""
        local key = KEYS[1]
        local ttl = tonumber(ARGV[1])
        local set = redis.call('SET', key, {UpdateLockState.PROCESSING.value}, 'PX', ttl, 'NX')

        if set then return 1 end

        local val = tonumber(redis.call('GET', key))

        if val == {UpdateLockState.HANDLED.value} then return 0 end

        return -1
    """
    # Returns:
    #   1  → lock acquired        (True)
    #   0  → already handled      (False)
    #  -1  → processing by other  (None / wait)

    def __init__(self, redis: 'Redis', *args, **kw) -> None:
        super().__init__(*args, **kw)

        self.lock_ttl = self.lock_ttl * 1000  #to milliseconds 
        self.redis = redis
        self.lua_acquire = self.redis.register_script(self.LUA_ACQUIRE_SCRIPT)

    async def _try_acquire(self, key):
        result = await self.lua_acquire(
            keys=[key],
            args=[self.lock_ttl],
        )

        if result == -1:
            return
        
        return bool(result)

    async def release(self, key, result = None):
        built_key = self.build_key(key)

        if result is None:
            await self.redis.delete(built_key)
        else:
            await self.redis.set(
                built_key, result.value, keepttl=True
            )