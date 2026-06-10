from typing import TYPE_CHECKING

from ..types import CallbackQuery
from .update_history import UpdateHistory




class CallbackQueryHistory(UpdateHistory[CallbackQuery]):
    __update_type__ = CallbackQuery
    
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
        m = update.message

        return (
            m 
            and m.chat is not None
        )
    

    async def _extract_key(self, update):
        m = update.message

        return (
            m.chat.id, 
            getattr(update.from_user, "id", None), 
            m.id
        )
    

    async def _extract_data(self, update):
        return update.data



