from abc import ABC
from typing import Optional, Callable, Type, Dict
from concurrent.futures import ThreadPoolExecutor

from ..utils.typings import UpdateType, MaybeCoroutineCallable
from ..utils import UpdateBound, maybe_awaitable

from ..enums import UpdateLockState
from ..typings import UpdateCoordinatorKeyT
from ..update_coordinator import UpdateCoordinator, MemoryUpdateCoordinator

import logging

log = logging.getLogger(__name__)

class UpdateCoordinated(ABC, UpdateBound[UpdateType]):
    """
    Abstract base for update types that require distributed deduplication.

    Each subclass is bound to a single update type via ``__update_type__``
    and defines whether an update should be coordinated and how to extract
    its coordination key. The coordinator factory is responsible for all
    locking details (backend, TTL, timeout).

    Each of the two core behaviours — coordinatability check and key
    extraction — can be provided either by overriding the corresponding
    method in a subclass, or by passing a callable at construction time
    via ``is_coordinatable_func`` or ``extract_key_func``.

    Parameters:
        coordinator_factory:   Optional callable that receives the update type and
                               returns a configured :class:`UpdateCoordinator` instance.
                               If ``None``, it defaults to creating a local
                               :class:`MemoryUpdateCoordinator`.
        is_coordinatable_func: Optional callable ``(update) -> bool`` used by
                               :meth:`is_coordinatable`. If ``None``, the method
                               must be overridden in a subclass.
        extract_key_func:      Optional callable ``(update) -> UpdateCoordinatorKeyT``
                               used by :meth:`extract_key`. If ``None``, the method
                               must be overridden in a subclass.
        **kw:                  Passed to the next class in the MRO.
    """

    def __init__(
        self,
        coordinator_factory: Optional[Callable[[Type[UpdateType]], UpdateCoordinator]] = None, 
        is_coordinatable_func: Optional[MaybeCoroutineCallable[[UpdateType], bool]] = None, 
        extract_key_func: Optional[MaybeCoroutineCallable[[UpdateType], UpdateCoordinatorKeyT]] = None, 
        **kw,
    ) -> None:
        
        super().__init__(**kw)

        if coordinator_factory is None:
            coordinator_factory = MemoryUpdateCoordinator
        
        self.coordinator = coordinator_factory(self.__class__.__update_type__)

        self.is_coordinatable_func = is_coordinatable_func
        self.extract_key_func = extract_key_func

        self._key_cache: Dict[int, Optional[UpdateCoordinatorKeyT]] = {}


    def _get_executor(self, update: UpdateType) -> Optional[ThreadPoolExecutor]:
        return getattr(
            getattr(update, "_client", None), 
            "executor", 
            None
        )

    async def is_coordinatable(self, update: UpdateType) -> bool:
        """
        Determine whether this update should be coordinated.

        Called before any key extraction or lock acquisition.
        Return ``False`` to process the update normally without a lock.

        Parameters:
            update: The incoming update object.

        Returns:
            ``True`` if the update should be coordinated, ``False`` otherwise.

        Raises:
            NotImplementedError: If neither this method is overridden nor
                                 ``is_coordinatable_func`` was provided.
        """

        if self.is_coordinatable_func is None:
            raise NotImplementedError(
                f"{self.__class__.__name__} must either pass is_coordinatable_func "
                f"or override is_coordinatable()"
            )
        
        self.validate_update(update)

        return await maybe_awaitable(
            self.is_coordinatable_func,
            update,
            executor=self._get_executor(update),
        )

    async def extract_key(self, update: UpdateType) -> UpdateCoordinatorKeyT:
        """
        Extract a unique coordination key from the update.

        Only called when :meth:`is_coordinatable` returns ``True``.
        The result is cached for the lifetime of the update object.

        Parameters:
            update: The incoming update object.

        Returns:
            A :data:`UpdateCoordinatorKeyT` that uniquely identifies
            this update.

        Raises:
            NotImplementedError: If neither this method is overridden nor
                                 ``extract_key_func`` was provided.
        """
        if self.extract_key_func is None:
            raise NotImplementedError(
                f"{self.__class__.__name__} must either pass extract_key_func "
                f"or override extract_key()"
            )
        
        self.validate_update(update)

        update_id = id(update)

        if update_id not in self._key_cache:
            self._key_cache[update_id] = await maybe_awaitable(
                self.extract_key_func,
                update,
                executor=self._get_executor(update),
            )

        return self._key_cache[update_id]

    async def _evict(self, update: UpdateType) -> None:
        """Remove the cached key for the given update."""
        self._key_cache.pop(id(update), None)

    async def acquire(self, update: UpdateType) -> Optional[bool]:
        """
        Acquire the lock for the given update.

        Parameters:
            update: The incoming update object.

        Returns:
            bool | None:
                - ``True``  — lock acquired, process the update then call release().
                - ``False`` — already handled by another session, skip it.
                - ``None``  — coordination not needed, process without release.

        Raises:
            TimeoutError: if waiting for the lock exceeds the allowed timeout.
        """

        if not await self.is_coordinatable(update):
            return None

        return await self.coordinator.acquire(
            await self.extract_key(update)
            )

    async def release(self, update: UpdateType, result: Optional[UpdateLockState] = None) -> None:
        """
        Release the lock after processing and evict the cached key.

        Parameters:
            update: The same update passed to :meth:`acquire`.
            result: ``UpdateLockState.HANDLED`` if processing succeeded,
                    ``None`` if it failed — key is deleted so another
                    session can retry.
        """

        try:
            if not await self.is_coordinatable(update):
                return

            await self.coordinator.release(
                await self.extract_key(update), 
                result
                )
        finally:
            await self._evict(update)

    async def start(self) -> None:
        """Start the coordinator."""
        await self.coordinator.start()

    async def stop(self) -> None:
        """Stop the coordinator."""
        await self.coordinator.stop()

        if self._key_cache:
            log.warning(
                "Clearing %d cached update keys after coordinator stop",
                len(self._key_cache),
            )
            self._key_cache.clear()