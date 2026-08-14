from typing import TYPE_CHECKING

from ..types import Message
from .update_history import UpdateHistory


class MessageHistory(UpdateHistory[Message]):
    __update_type__ = Message

    if not TYPE_CHECKING:
        def __init__(self, *args, **kw):
            super().__init__(*args, **kw)
            
            if self.is_recordable_func is None:
                self.is_recordable_func = self._is_recordable

            if self.extract_key_func is None:
                self.extract_key_func = self._extract_key

            if self.extract_data_func is None:
                self.extract_data_func = self._extract_data

            

    async def _is_recordable(self, update):
        return update.chat is not None

    async def _extract_key(self, update):
        return (
            update.chat.id,
            getattr(update.from_user, "id", None),
            update.id,
        )

    async def _extract_data(self, update):
        return update.text
