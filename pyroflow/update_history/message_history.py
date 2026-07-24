from typing import TYPE_CHECKING

from ..types import Message
from .update_history import UpdateHistory


class MessageHistory(UpdateHistory[Message]):
    __update_type__ = Message

    if not TYPE_CHECKING:
        def __init__(
            self,
            store_factory = None,
            is_recordable_func = None,
            extract_key_func = None,
            extract_data_func = None,
            **kw
            ):

            if is_recordable_func is None:
                is_recordable_func = self._is_recordable

            if extract_key_func is None:
                extract_key_func = self._extract_key

            if extract_data_func is None:
                extract_data_func = self._extract_data

            super().__init__(store_factory, is_recordable_func, extract_key_func, extract_data_func, **kw)

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
