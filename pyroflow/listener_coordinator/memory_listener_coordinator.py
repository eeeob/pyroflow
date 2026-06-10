from itertools import count

from ..utils import AsyncioLock
from .listener_coordinator import ListenerCoordinator

import logging
import weakref

log = logging.getLogger(__name__)


class MemoryListenerCoordinator(ListenerCoordinator):
    def __init__(self, listener):
        super().__init__(listener)

        self.locks = weakref.WeakValueDictionary()
        self.data = {}
        self.counter = count()
    
    def lock(self, key):
        _lock = self.locks.get(key)
        
        if _lock is None:
            _lock = AsyncioLock()
            self.locks[key] = _lock
            
        return _lock
    

    def _register(self, key):
        if self._registered(key):
            raise KeyError(f"Key {key} already registered")
        
        _id = next(self.counter)
        self.data[key] = _id

        return _id

    def _unregister(self, key, coordinator_id = None):
        if (r_id := self.data.pop(key, None)) is not None:
            if coordinator_id is not None and coordinator_id != r_id:
                self.data[key] = r_id
                return False
        
        return True
    
    def _cancel(self, key):
        return self._unregister(key)

    def _registered(self, key, coordinator_id = None):
        if (r_id := self.data.get(key)) is not None:
            return coordinator_id is None or r_id == coordinator_id
        
        return False
    
    async def register(self, *args, **kw):
        return self._register(*args, **kw)
    
    async def unregister(self, *args, **kw):
        return self._unregister(*args, **kw)
    
    async def cancel(self, *args, **kw):
        return self._cancel(*args, **kw)
    
    async def registered(self, *args, **kw):
        return self._registered(*args, **kw)

    async def stop(self):
        self.counter = count()

        if self.data:
            log.warning("MemoryListenerCoordinator stopped with pending registrations: %s", list(self.data.keys()))
        
        self.data.clear()
