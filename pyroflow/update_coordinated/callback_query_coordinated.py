from typing import TYPE_CHECKING

from ..types import CallbackQuery
from .update_coordinated import UpdateCoordinated


class CallbackQueryCoordinated(UpdateCoordinated[CallbackQuery]):
    __update_type__ = CallbackQuery

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
        Lock per query, so queries never wait on each other.

        Pass ``extract_key_func`` to serialise a wider scope instead — e.g.
        the originating chat — without affecting deduplication, which keys
        on :meth:`_extract_update_id` independently.
        """

        return (update.id, )

    async def _extract_update_id(self, update):
        return (update.id, )

    async def _is_coordinatable(self, update):
        return True
