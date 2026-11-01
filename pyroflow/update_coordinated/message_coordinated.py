"""Coordination policy for :class:`Message` updates."""

from __future__ import annotations as _annotations
from typing import TYPE_CHECKING, Any
from pyrogram.utils import get_peer_id

from ..types import Message
from .update_coordinated import UpdateCoordinated

if TYPE_CHECKING:
    from ..typings import UpdateCoordinatorKeyT


class MessageCoordinated(UpdateCoordinated[Message]):
    """Coordinates messages, locked and deduplicated per message by default."""

    __update_type__ = Message

    if not TYPE_CHECKING:

        def __init__(self, *args: Any, **kw: Any) -> None:
            """Initialise the policy, defaulting any callable not passed to this class's own."""
            super().__init__(*args, **kw)

            if self.is_coordinatable_func is None:
                self.is_coordinatable_func = self._is_coordinatable

            if self.extract_key_func is None:
                self.extract_key_func = self._extract_key

            if self.extract_update_id_func is None:
                self.extract_update_id_func = self._extract_update_id

    async def _extract_key(self, update: Message) -> UpdateCoordinatorKeyT:
        """Lock per message, so messages never wait on each other.

        Pass ``extract_key_func=lambda m: (get_peer_id(m.raw.peer_id),)`` to
        serialise a whole chat instead — deduplication is unaffected, since
        it keys on :meth:`_extract_update_id` independently.
        """
        return (get_peer_id(update.raw.peer_id), update.id)  # ty: ignore[unresolved-attribute]  # pyrogram types Message.raw as Optional; dispatched messages always carry it

    async def _extract_update_id(self, update: Message) -> UpdateCoordinatorKeyT:
        return (get_peer_id(update.raw.peer_id), update.id)  # ty: ignore[unresolved-attribute]  # pyrogram types Message.raw as Optional; dispatched messages always carry it

    async def _is_coordinatable(self, update: Message) -> bool:
        return True


__all__ = ("MessageCoordinated",)
