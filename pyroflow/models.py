from typing import Tuple, Optional, Any, Generator
from dataclasses import dataclass, field
from pyrogram.handlers import Handler as PyroHandler

from .utils.typings import JsonValueT, Number

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

