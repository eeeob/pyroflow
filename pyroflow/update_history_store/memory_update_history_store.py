"""In-memory handler history store with per-record TTL and an LRU key cap."""

from __future__ import annotations as _annotations
from typing import TYPE_CHECKING, Any

from cachetools import TTLCache

from pytrove.enums import TimeUnit

from .update_history_store import UpdateHistoryStore

import heapq
import time

if TYPE_CHECKING:
    from pytrove.typings import Number

    from ..typings import UpdateType, UpdateHistoryKeyT
    from ..models import UpdateRecord


class MemoryUpdateHistoryStore(UpdateHistoryStore):
    """In-memory history store bounded by both age and key count.

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
        update_type: type[UpdateType],
        ttl: Number = TimeUnit.DAY / 2,
        max_history_len: int = 2,
        max_keys: int = 1000,
        **kw: Any,
    ) -> None:
        """Create the store and its bounded key cache."""
        super().__init__(update_type, **kw)

        self.ttl = ttl
        self.max_history_len = max_history_len

        self.histories: TTLCache[UpdateHistoryKeyT, list[UpdateRecord]] = TTLCache(
            maxsize=max_keys, ttl=ttl
        )

    def _expires_at(self, record: UpdateRecord) -> Number:
        return record.created_at + self.ttl

    def _is_expired(self, record: UpdateRecord, now: Number | None = None) -> bool:
        return (time.time() if now is None else now) >= self._expires_at(record)

    def _clean_up(self, heap: list[UpdateRecord], now: Number | None = None) -> list[UpdateRecord]:
        if now is None:
            now = time.time()

        while heap and self._is_expired(heap[0], now):
            heapq.heappop(heap)

        return heap

    def _update(self, key: UpdateHistoryKeyT, *records: UpdateRecord) -> None:
        heap = self.histories.setdefault(key, [])

        for record in records:
            heapq.heappush(heap, record)

        heap = self._clean_up(heap)

        while len(heap) > self.max_history_len:
            heapq.heappop(heap)

        if not heap:
            self._delete(key)

    def _get(self, key: UpdateHistoryKeyT) -> list[UpdateRecord]:
        records = sorted(self._clean_up(self.histories.get(key, [])))

        if not records:
            self._delete(key)

        return records

    def _pop(self, key: UpdateHistoryKeyT) -> list[UpdateRecord]:
        return sorted(self._clean_up(self.histories.pop(key, [])))

    def _delete(self, key: UpdateHistoryKeyT) -> None:
        self.histories.pop(key, None)

    async def update(self, key: UpdateHistoryKeyT, *records: UpdateRecord) -> None:
        """Add records under ``key``, dropping expired ones and the oldest past the limit."""
        return self._update(key, *records)

    async def get(self, key: UpdateHistoryKeyT) -> list[UpdateRecord]:
        """Return the unexpired records under ``key``, oldest first."""
        return self._get(key)

    async def pop(self, key: UpdateHistoryKeyT) -> list[UpdateRecord]:
        """Remove ``key`` and return its unexpired records, oldest first."""
        return self._pop(key)

    async def delete(self, key: UpdateHistoryKeyT) -> None:
        """Delete all records under ``key``."""
        return self._delete(key)


__all__ = ("MemoryUpdateHistoryStore",)
