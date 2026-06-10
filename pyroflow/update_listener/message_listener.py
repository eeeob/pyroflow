from typing import TYPE_CHECKING

from ..models import ListenerKey
from ..types import Message

from .update_listener import UpdateListener



class MessageListener(UpdateListener[Message]):
    __update_type__ = Message

    if not TYPE_CHECKING:
        def __init__(
            self, 
            coordinator_factory = None, 
            duplicate_policy = None, 
            is_listenable_func = None, 
            extract_key_func = None, 
            timeout = None, 
            **kw
            ):

            if is_listenable_func is None:
                is_listenable_func = self._is_listenable
            
            if extract_key_func is None:
                extract_key_func = self._extract_key

            super().__init__(coordinator_factory, duplicate_policy, is_listenable_func, extract_key_func, timeout, **kw)


    async def _is_listenable(self, update):
        return not (
            update.outgoing 
            or update.service 
            or getattr(update.from_user, "is_self", False) 
            or update.empty 
            or update.edit_date 
            or update.edit_hidden 
            or update.chat is None
        )

    async def _extract_key(self, update):
        return ListenerKey(
            update.chat.id, 
            update.from_user.id, 
            update.id
        )