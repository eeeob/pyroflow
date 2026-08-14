from typing import List, Optional
from cachetools import TTLCache

from ..utils.typings import Number
from ..utils.enums import TimeUnit

from ..typings import UpdateHistoryKeyT
from ..models import UpdateRecord

from .update_history_store import UpdateHistoryStore

import heapq
import time


class MemoryUpdateHistoryStore(UpdateHistoryStore):
    """
    In-memory history store bounded by both age and key count.

    Per-record ``ttl`` is enforced lazily, on access to that key. That alone
    cannot reclaim a key that is written once and never read again, so the
    key space itself is additionally capped by ``max_keys`` (LRU) and the
    same ``ttl`` — otherwise a long-running bot accumulates one entry per
    conversation, forever.

    Parameters:
        update_type:     The Pyrogram update class this store handles.
        ttl:             Seconds a record (and an idle key) stays valid.
        max_history_len: Max records kept per key.
        max_keys:        Max distinct keys retained; least-recently-used
                         keys are evicted past this bound.
    """

    def __init__(
        self,
        update_type,
        ttl: Number = TimeUnit.DAY / 2,
        max_history_len: int = 2,
        max_keys: int = 1000,
        **kw
    ):
        super().__init__(update_type, **kw)

        self.ttl = ttl
        self.max_history_len = max_history_len

        self.histories: TTLCache[UpdateHistoryKeyT, List[UpdateRecord]] = TTLCache(
            maxsize=max_keys, ttl=ttl
        )

    def _expires_at(self, record: UpdateRecord) -> Number:
        return record.created_at + self.ttl
    
    def _is_expired(self, record: UpdateRecord, now: Optional[Number] = None) -> bool:
        return (time.time() if now is None else now) >= self._expires_at(record)

    def _clean_up(self, heap: List[UpdateRecord], now: Optional[Number] = None) -> List[UpdateRecord]:
        if now is None:
            now = time.time()

        while heap and self._is_expired(heap[0], now):
            heapq.heappop(heap)

        return heap


    def _update(self, key, *records):
        heap = self.histories.setdefault(key, [])

        for record in records:
            heapq.heappush(heap, record)

        heap = self._clean_up(heap)

        while len(heap) > self.max_history_len:
            heapq.heappop(heap)

        if not heap:
            self._delete(key)

    def _get(self, key):
        records = sorted(self._clean_up(self.histories.get(key, [])))

        if not records:
            self._delete(key)

        return records

    def _pop(self, key):
        return sorted(self._clean_up(self.histories.pop(key, [])))

    def _delete(self, key):
        self.histories.pop(key, None)
    

    async def update(self, *args, **kw):
        return self._update(*args, **kw)
        
    async def get(self, *args, **kw):
        return self._get(*args, **kw)
    
    async def pop(self, *args, **kw):
        return self._pop(*args, **kw)
        
    async def delete(self, *args, **kw):
        return self._delete(*args, **kw)