from typing import TYPE_CHECKING
from pyrogram.utils import get_peer_id

from ..types import Message
from .update_coordinated import UpdateCoordinated



class MessageCoordinated(UpdateCoordinated[Message]):
    __update_type__ = Message

    if not TYPE_CHECKING:

        def __init__(
            self, 
            coordinator_factory = None, 
            is_coordinatable_func = None, 
            extract_key_func = None, 
            **kw
            ):

            if is_coordinatable_func is None:
                is_coordinatable_func = self._is_coordinatable
            
            if extract_key_func is None:
                extract_key_func = self._extract_key

            super().__init__(coordinator_factory, is_coordinatable_func, extract_key_func, **kw)


    async def _extract_key(self, update):
        return (
            get_peer_id(update.raw.peer_id), 
            update.id
        )
    
    async def _is_coordinatable(self, update):
        return True