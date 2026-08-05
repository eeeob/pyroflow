from typing import MutableMapping, Optional, Union, List
from sortedcontainers import SortedList
from functools import partial
from cachetools import TTLCache

from ..utils.typings import Number
from ..utils.enums import TimeUnit

from ..typings import UpdateHistoryKeyT
from ..models import UpdateRecord

from .update_history_store import UpdateHistoryStore

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
        max_keys: int = 10_000,
        **kw
    ):
        super().__init__(update_type, **kw)

        self.ttl = ttl
        self.max_history_len = max_history_len

        self.s_list_factory = partial(SortedList, key=lambda r: r.created_at)
        # TTLCache bounds the key space; per-record expiry is still handled
        # by _clean_up, since records within one key expire independently.
        self.histories: MutableMapping[UpdateHistoryKeyT, SortedList] = TTLCache(
            maxsize=max_keys, ttl=ttl
        )

    def _expires_at(self, record: UpdateRecord) -> Number:
        return record.created_at + self.ttl
    
    def _is_expired(self, record: UpdateRecord, now: Optional[Number] = None) -> bool:
        if now is None:
            now = time.time()
        
        return now >= self._expires_at(record)

    def _clean_up(
        self, 
        records: Union[SortedList, List], 
        just_copy: bool = False, 
        now: Optional[Number] = None
        ) -> Union[SortedList, List]:

        if now is None:
            now = time.time()
        
        if just_copy:
            return [
                r for r in records
                if not self._is_expired(r, now)
            ]

        i = 0

        while i < len(records):
            if self._is_expired(records[i], now):
                records.pop(i)
            else:
                i += 1
        
        return records


    def _update(self, key, *records):
        s_list = self.histories.get(key)

        if s_list is None:
            s_list = self.s_list_factory()
            self.histories[key] = s_list

        s_list.update(records)
        s_list = self._clean_up(s_list, False)

        while len(s_list) > self.max_history_len:
            s_list.pop(0)
        
        if not s_list:
            self._delete(key)

    def _get(self, key):
        s_list = self._clean_up(
            self.histories.get(key, []), 
            True
            )

        if not s_list:
            self._delete(key)
        
        return s_list

    def _pop(self, key):
        s_list = self._clean_up(
            self.histories.pop(key, []), 
            True
            )
        
        return s_list

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