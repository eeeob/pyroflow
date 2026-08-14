from typing import TYPE_CHECKING
from pyrogram.utils import get_peer_id

from ..types import Message
from .update_coordinated import UpdateCoordinated



class MessageCoordinated(UpdateCoordinated[Message]):
    __update_type__ = Message

    if not TYPE_CHECKING:
        def __init__(self, *args, **kw):
            super().__init__(*args, **kw)

            if self.is_coordinatable_func is None:
                self.is_coordinatable_func = self._is_coordinatable

            if self.extract_key_func is None:
                self.extract_key_func = self._extract_key

            if self.extract_update_id_func is None:
                self.extract_update_id_func = self._extract_update_id


    async def _extract_key(self, update):
        """
        Lock per message, so messages never wait on each other.

        Pass ``extract_key_func=lambda m: (get_peer_id(m.raw.peer_id),)`` to
        serialise a whole chat instead — deduplication is unaffected, since
        it keys on :meth:`_extract_update_id` independently.
        """

        return (
            get_peer_id(update.raw.peer_id),
            update.id
        )

    async def _extract_update_id(self, update):
        return (
            get_peer_id(update.raw.peer_id),
            update.id
        )

    async def _is_coordinatable(self, update):
        return True
