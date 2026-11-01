"""Abstract base class for handler history storage backends."""

from __future__ import annotations as _annotations

from abc import ABC, abstractmethod
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Sequence

    from ..models import UpdateRecord
    from ..typings import UpdateType, UpdateHistoryKeyT


class UpdateHistoryStore(ABC):
    """Store, read and expire `UpdateRecord` entries under history keys.

    Each backend sets its own capacity and TTL.

    Args:
        update_type: The Pyrogram update class this store handles.
        **kw: Passed to the next class in the MRO.
    """

    def __init__(self, update_type: type[UpdateType], **kw: Any) -> None:
        """Bind the store to its update type."""
        self.update_type = update_type
        """Pyrogram update class whose records this store holds."""

        super().__init__(**kw)

    @abstractmethod
    async def update(self, key: UpdateHistoryKeyT, *records: UpdateRecord) -> None:
        """Save records under `key`.

        Args:
            key: The history key.
            *records: The records to save.
        """
        raise NotImplementedError

    @abstractmethod
    async def get(self, key: UpdateHistoryKeyT) -> Sequence[UpdateRecord]:
        """Return the unexpired records under `key`.

        Args:
            key: The history key.

        Returns:
            The records, oldest first; empty if there are none.
        """
        raise NotImplementedError

    @abstractmethod
    async def pop(self, key: UpdateHistoryKeyT) -> Sequence[UpdateRecord]:
        """Remove every record under `key` and return the unexpired ones.

        Args:
            key: The history key.

        Returns:
            The removed records, oldest first; empty if there were none.
        """
        raise NotImplementedError

    @abstractmethod
    async def delete(self, key: UpdateHistoryKeyT) -> None:
        """Delete every record under `key`.

        Args:
            key: The history key.
        """
        raise NotImplementedError

    async def start(self) -> None:  # noqa: B027  # optional hook; backends override it when needed
        """Start the store. Override to initialise backend connections."""

    async def stop(self) -> None:  # noqa: B027  # optional hook; backends override it when needed
        """Stop the store. Override to close backend connections."""


__all__ = ("UpdateHistoryStore",)
