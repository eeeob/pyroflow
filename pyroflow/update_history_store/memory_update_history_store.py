from typing import Dict, Optional, Union, List
from sortedcontainers import SortedList
from functools import partial

from ..utils.typings import Number
from ..utils.enums import TimeUnit

from ..typings import UpdateHistoryKeyT
from ..models import UpdateRecord

from .update_history_store import UpdateHistoryStore

import time


class MemoryUpdateHistoryStore(UpdateHistoryStore):
    def __init__(
        self, 
        update_type, 
        ttl: Number = TimeUnit.DAY / 2, 
        max_history_len: int = 2, 
        **kw
    ):
        super().__init__(update_type, **kw)

        self.ttl = ttl
        self.max_history_len = max_history_len

        self.s_list_factory = partial(SortedList, key=lambda r: r.created_at)
        self.histories: Dict[UpdateHistoryKeyT, SortedList] = {}

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