from typing import Sequence, Type
from abc import ABC, abstractmethod

from ..utils.typings import UpdateType

from ..typings import UpdateHistoryKeyT
from ..models import UpdateRecord




class UpdateHistoryStore(ABC):
    """
    Abstract base for handler history storage backends.

    Responsible for persisting, retrieving, and expiring
    :class:`UpdateRecord` entries under arbitrary UpdateHistoryKeyT keys.

    Capacity and TTL settings are left to each concrete backend.

    Parameters:
        update_type: The Pyrogram update class this store handles.
                    Its name is used to namespace the storage keys.
        **kw:        Passed to the next class in the MRO.
    """

    def __init__(self, update_type: Type[UpdateType], **kw) -> None:
        self.update_type = update_type

        super().__init__(**kw)


    @abstractmethod
    async def update(self, key: UpdateHistoryKeyT, *records: UpdateRecord) -> None:
        """
        save records under the given key.

        Parameters:
            key: An arbitrary UpdateHistoryKeyT identifying the (chat, user) context.
            *records: The :class:`UpdateRecord` to persist.
        """
        raise NotImplementedError

    @abstractmethod
    async def get(self, key: UpdateHistoryKeyT) -> Sequence[UpdateRecord]:
        """
        Load all records stored under the given key.

        Expired records must not be returned.

        Parameters:
            key: The storage key to retrieve records for.

        Returns:
            A sequence of :class:`UpdateRecord` ordered from oldest
            to newest, or an empty sequence if none exist.
        """
        raise NotImplementedError
    
    @abstractmethod
    async def pop(self, key: UpdateHistoryKeyT) -> Sequence[UpdateRecord]:
        """
        Remove and return the newest record stored under the given key.

        Expired records must not be returned. If all records are expired,
        they should be discarded before attempting to pop.

        Parameters:
            key: The storage key to pop a record from.

        Returns:
            A sequence of :class:`UpdateRecord` ordered from oldest
            to newest, or an empty sequence if none exist.
        """
        raise NotImplementedError

    @abstractmethod
    async def delete(self, key: UpdateHistoryKeyT) -> None:
        """
        Delete all records stored under the given key.

        Parameters:
            key: The storage key whose records should be deleted.
        """
        raise NotImplementedError

    async def start(self) -> None:
        """Start the store. Override to initialise backend connections."""
        pass

    async def stop(self) -> None:
        """Stop the store. Override to close backend connections."""
        pass
