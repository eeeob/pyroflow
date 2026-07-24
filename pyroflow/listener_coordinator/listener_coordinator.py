from abc import ABC, abstractmethod
from typing import Optional, Union, Tuple, TypeAlias, TYPE_CHECKING


from ..utils.typings import AsyncLockProto
from ..typings import ListenerCoordinatorIdT
from ..models import ListenerKey

if TYPE_CHECKING:
    from ..update_listener import UpdateListener


LockKeyT: TypeAlias = Union[int, Tuple[Optional[int], ...], ListenerKey]

class ListenerCoordinator(ABC):
    """
    Abstract base for listener registries.

    A listener coordinator stores and manages registrations for update listeners.
    Concrete implementations must provide locking, listener coordinator,
    unregistration and lookup semantics appropriate for their storage
    backend (in-memory, Redis, etc.).

    All mutating operations on the same chat should be performed under
    the lock returned by :meth:`lock` to prevent races between
    listener coordinator, cancellation and update resolution.

    Parameters:
        listener: The :class:`UpdateListener` that owns this listener coordinator.
        **kw:     Passed to the next class in the MRO.
    """

    def __init__(self, listener: "UpdateListener", **kw):
        super().__init__(**kw)

        self.listener = listener
        
    @abstractmethod
    def lock(self, key: LockKeyT) -> AsyncLockProto:
        """
        Return an async context manager that serialises listener coordinator
        operations for the given key.

        The returned object must support ``async with`` semantics.

        Parameters:
            key: A chat id, a tuple of ids, or a :class:`ListenerKey`
                 identifying the scope to lock.

        Returns:
            An async lock compatible with ``async with``.
        """
        raise NotImplementedError
    
    @abstractmethod
    async def register(self, key: ListenerKey) -> ListenerCoordinatorIdT:
        """
        Register a listener for the given key and return a unique
        listener coordinator id.

        The listener coordinator id can later be passed to :meth:`unregister`
        to safely remove this specific listener coordinator without affecting
        a newer one that may have replaced it.

        Parameters:
            key: The :class:`ListenerKey` to register.

        Returns:
            A unique identifier for this listener coordinator.
        """
        raise NotImplementedError
    
    @abstractmethod
    async def unregister(self, key: ListenerKey, coordinator_id: Optional[ListenerCoordinatorIdT] = None) -> bool:
        """
        Remove a listener coordinator by key and optional listener coordinator id.

        If ``coordinator_id`` is provided, only the listener coordinator
        matching that id is removed, preventing accidental removal
        of a newer listener coordinator for the same key.

        Parameters:
            key:             The :class:`ListenerKey` to unregister.
            coordinator_id: If provided, only remove the listener coordinator
                             with this id.

        Returns:
            ``True`` if a listener coordinator was removed, ``False`` otherwise.
        """
        raise NotImplementedError
    
    @abstractmethod
    async def cancel(self, key: ListenerKey) -> bool:
        """
        Cancel all registrations for the given key.

        Parameters:
            key: The :class:`ListenerKey` whose registrations should
                 be cancelled.

        Returns:
            ``True`` if any registrations were cancelled, ``False``
            otherwise.
        """
        raise NotImplementedError
    
    @abstractmethod
    async def registered(self, key: ListenerKey, coordinator_id: Optional[ListenerCoordinatorIdT] = None) -> bool:
        """
        Check whether a listener coordinator exists for the given key.

        Parameters:
            key:             The :class:`ListenerKey` to check.
            coordinator_id: If provided, also verify that the listener coordinator
                             matches this specific id.

        Returns:
            ``True`` if a matching listener coordinator exists, ``False`` otherwise.
        """
        raise NotImplementedError
    

    async def start(self) -> None:
        pass

    async def stop(self) -> None:
        pass
    
    
    
    
    
    











