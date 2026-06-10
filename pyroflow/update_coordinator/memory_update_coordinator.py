from threading import RLock
from cachetools import TLRUCache

from ..enums import UpdateLockState
from .update_coordinator import UpdateCoordinator


class MemoryUpdateCoordinator(UpdateCoordinator):
    def __init__(self, *args, **kw) -> None:
        super().__init__(*args, **kw)

        self.lock = RLock() 
        self.data: TLRUCache[str, UpdateLockState] = TLRUCache(
            1000 * 10, 
            lambda _, __, mono: mono + self.lock_ttl
        )

    async def _try_acquire(self, key):
        with self.lock:
            if key in self.data:
                state = self.data[key]

                if state == UpdateLockState.HANDLED:
                    return False
                
                return
            
            self.data[key] = UpdateLockState.PROCESSING
            return True


    async def release(self, key, result = None):
        built_key = self.build_key(key)

        with self.lock:
            if result is None:
                self.data.pop(built_key, None)
            else:
                self.data[built_key] = result
    

    async def stop(self):
        self.data.clear()