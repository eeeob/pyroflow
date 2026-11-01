"""In-memory handler history store with per-record TTL and an LRU key cap."""

from __future__ import annotations as _annotations

import heapq
import time
from typing import Any, TYPE_CHECKING

from cachetools import TTLCache
from pytrove.enums import TimeUnit

from .update_history_store import UpdateHistoryStore

if TYPE_CHECKING:
    from pytrove.typings import Number

    from ..models import UpdateRecord
    from ..typings import UpdateType, UpdateHistoryKeyT


class MemoryUpdateHistoryStore(UpdateHistoryStore):
    """In-memory history store bounded by both age and key count.

    Per-record ``ttl`` is enforced lazily, on access to that key. That alone
    cannot reclaim a key that is written once and never read again, so the
    key space itself is additionally capped by ``max_keys`` (LRU) and the
    same ``ttl`` — otherwise a long-running bot accumulates one entry per
    conversation, forever.

    Args:
        update_type: The Pyrogram update class this store handles.
        ttl: Seconds a record (and an idle key) stays valid.
        max_history_len: Max records kept per key.
        max_keys: Max distinct keys retained; least-recently-used keys are
            evicted past this bound.
        **kw: Passed to the next class in the MRO.

    Example:
        >>> import asyncio
        >>> from pyroflow.models import UpdateRecord
        >>> from pyroflow.types import Message
        >>> store = MemoryUpdateHistoryStore(Message, max_history_len=2)
        >>> async def demo():
        ...     await store.update("key", *(UpdateRecord(handler=h) for h in "abc"))
        ...     return [record.handler for record in await store.get("key")]
        >>> asyncio.run(demo())
        ['b', 'c']
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
        """Return the time at which ``record`` expires."""
        return record.created_at + self.ttl

    def _is_expired(self, record: UpdateRecord, now: Number | None = None) -> bool:
        """Return whether ``record`` has expired at ``now``, or at the current time if ``None``."""
        return (time.time() if now is None else now) >= self._expires_at(record)

    def _clean_up(self, heap: list[UpdateRecord], now: Number | None = None) -> list[UpdateRecord]:
        """Pop expired records off the front of ``heap`` in place and return it."""
        if now is None:
            now = time.time()

        while heap and self._is_expired(heap[0], now):
            heapq.heappop(heap)

        return heap

    def _update(self, key: UpdateHistoryKeyT, *records: UpdateRecord) -> None:
        """Push ``records`` under ``key``, then drop expired and oldest-past-the-limit ones."""
        heap = self.histories.setdefault(key, [])

        for record in records:
            heapq.heappush(heap, record)

        heap = self._clean_up(heap)

        while len(heap) > self.max_history_len:
            heapq.heappop(heap)

        if not heap:
            self._delete(key)

    def _get(self, key: UpdateHistoryKeyT) -> list[UpdateRecord]:
        """Return the unexpired records under ``key``, oldest first, dropping the key if none."""
        records = sorted(self._clean_up(self.histories.get(key, [])))

        if not records:
            self._delete(key)

        return records

    def _pop(self, key: UpdateHistoryKeyT) -> list[UpdateRecord]:
        """Remove ``key`` and return its unexpired records, oldest first."""
        return sorted(self._clean_up(self.histories.pop(key, [])))

    def _delete(self, key: UpdateHistoryKeyT) -> None:
        """Remove ``key`` if present."""
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
