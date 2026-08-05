from typing import Tuple, Optional, Any, Generator
from dataclasses import dataclass, field
from pyrogram.handlers import Handler as PyroHandler

from .utils.typings import JsonValueT, Number
from .typings import ListenerCoordinatorIdT

import asyncio
import time


@dataclass(frozen=True, slots=True, eq=False)
class ListenerKey:
    chat_id: int
    user_id: Optional[int] = None
    message_id: Optional[int] = None

    @property
    def to_tuple(self) -> Tuple[int, Optional[int], Optional[int]]:
        return (
            self.chat_id,
            self.user_id,
            self.message_id
        )


    def sub_keys(self, min_dep: int = 1) -> Generator["ListenerKey", None, None]:
        keys = self.to_tuple
        current_len = len(keys)

        for i in range(current_len, min_dep - 1, -1):
            yield ListenerKey(
                *keys[:i]
            )

    def __hash__(self):
        return hash(self.to_tuple)

    def __eq__(self, value):
        return isinstance(value, ListenerKey) and self.to_tuple == value.to_tuple

@dataclass(slots=True)
class ListenerModel:
    key: ListenerKey
    meta: Optional[JsonValueT] = None
    future: asyncio.Future = field(default_factory=asyncio.Future)

    # Ownership token handed out by the coordinator at registration time.
    # A ListenerKey names *which* conversation slot this is; the id names
    # *which generation* of it. Cancellation travels between sessions
    # asynchronously, so a key alone cannot tell a live listener apart from
    # one that was superseded while a signal was still in flight — both
    # resolve() and _cancel() compare this token to stay on the right one.
    coordinator_id: Optional[ListenerCoordinatorIdT] = None


    def resolve(self, update) -> None:
        self.future.set_result(update)

    def set_exc(self, exc: Exception) -> None:
        self.future.set_exception(exc)

    def done(self) -> bool:
        return self.future.done()

@dataclass(slots=True)
class UpdateRecord:
    handler: PyroHandler
    data: Optional[Any] = None

    created_at: Number = field(default_factory=time.time)

