from abc import ABC
from typing import Optional, Callable, Type
from concurrent.futures import ThreadPoolExecutor

from ..utils.typings import UpdateType, MaybeCoroutineCallable, AsyncLockProto
from ..utils import UpdateBound, maybe_awaitable

from ..typings import UpdateCoordinatorKeyT
from ..update_coordinator import UpdateCoordinator, MemoryUpdateCoordinator

import logging

log = logging.getLogger(__name__)


class UpdateCoordinated(ABC, UpdateBound[UpdateType]):
    """
    Abstract base for update types that are processed under coordination.

    Each subclass is bound to a single update type via ``__update_type__``
    and defines three things: whether an update should be coordinated at
    all, what scope to serialise it under, and what identifies the update
    itself. The coordinator factory owns all backend details (locking,
    TTLs, timeouts).

    The two keys are deliberately separate
    -------------------------------------
    :meth:`extract_key` decides **what is locked** — the scope processed one
    update at a time. :meth:`extract_update_id` decides **what counts as
    the same update** — the identity registered as handled so it is never
    processed twice.

    By default both return the same thing, so an update is locked and
    deduplicated at exactly its own granularity: updates never block each
    other, and each is handled once. That is the narrow, safe default.

    Widening only :meth:`extract_key` is what buys ordering. Key the lock on
    the chat and every update in that chat is processed strictly one at a
    time, in arrival order, while :meth:`extract_update_id` keeps each one
    individually deduplicated. This is why the identity may never be folded
    into the lock's scope: a chat-wide *lock* serialises, but a chat-wide
    *identity* would register the whole chat as handled after its first
    update and silently drop every update that followed.

    Nothing constrains the two to be related — the scope may be as wide or
    narrow as the subclass wants, independently of the identity.

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
        extract_update_id_func: Optional callable ``(update) -> UpdateCoordinatorKeyT``
                               used by :meth:`extract_update_id`. If ``None``, the
                               method must be overridden in a subclass.
        **kw:                  Passed to the next class in the MRO.
    """

    def __init__(
        self,
        coordinator_factory: Optional[Callable[[Type[UpdateType]], UpdateCoordinator]] = None,
        is_coordinatable_func: Optional[MaybeCoroutineCallable[[UpdateType], bool]] = None,
        extract_key_func: Optional[MaybeCoroutineCallable[[UpdateType], UpdateCoordinatorKeyT]] = None,
        extract_update_id_func: Optional[MaybeCoroutineCallable[[UpdateType], UpdateCoordinatorKeyT]] = None,
        **kw,
    ) -> None:

        super().__init__(**kw)

        if coordinator_factory is None:
            coordinator_factory = MemoryUpdateCoordinator

        self.coordinator = coordinator_factory(self.__class__.__update_type__)

        self.is_coordinatable_func = is_coordinatable_func
        self.extract_key_func = extract_key_func
        self.extract_update_id_func = extract_update_id_func

    def _get_executor(self, update: UpdateType) -> Optional[ThreadPoolExecutor]:
        return getattr(
            getattr(update, "_client", None),
            "executor",
            None
        )

    async def is_coordinatable(self, update: UpdateType) -> bool:
        """
        Determine whether this update should be coordinated.

        Called before any key extraction or locking. Return ``False`` to
        process the update normally, with no lock and no registration.

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
        Extract the **lock scope** for this update.

        Every update that yields the same key is processed one at a time, in
        arrival order. Widen this to serialise a whole conversation; leave it
        at the update's own granularity to let updates run concurrently.

        This is not the update's identity — see :meth:`extract_update_id`.

        Parameters:
            update: The incoming update object.

        Returns:
            A :data:`UpdateCoordinatorKeyT` naming the scope to serialise.

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

        return await maybe_awaitable(
            self.extract_key_func, update,
            executor=self._get_executor(update),
        )

    async def extract_update_id(self, update: UpdateType) -> UpdateCoordinatorKeyT:
        """
        Extract the **identity** of this update, for deduplication.

        Registered once the update has been processed, and checked before
        processing it, so the same update is never handled twice — including
        across sessions, when the coordinator backend is shared.

        Must stay unique per update. Unlike :meth:`extract_key`, widening
        this does not serialise anything; it makes distinct updates look
        like the same one, and every update after the first is dropped as an
        already-handled duplicate.

        Parameters:
            update: The incoming update object.

        Returns:
            A :data:`UpdateCoordinatorKeyT` uniquely identifying this update.

        Raises:
            NotImplementedError: If neither this method is overridden nor
                                 ``extract_update_id_func`` was provided.
        """

        if self.extract_update_id_func is None:
            raise NotImplementedError(
                f"{self.__class__.__name__} must either pass extract_update_id_func "
                f"or override extract_update_id()"
            )

        self.validate_update(update)

        return await maybe_awaitable(
            self.extract_update_id_func, update,
            executor=self._get_executor(update),
        )

    async def lock(self, update: UpdateType) -> AsyncLockProto:
        """
        Build the lock serialising this update's scope.

        Returned unacquired — the caller decides when to take it and, more
        importantly, when to let it go (see :func:`~pyroflow.mark_handled`).

        Parameters:
            update: The incoming update object.

        Returns:
            An async lock compatible with ``async with``.
        """

        return self.coordinator.lock(
            await self.extract_key(update)
        )

    async def start(self) -> None:
        """Start the coordinator."""
        await self.coordinator.start()

    async def stop(self) -> None:
        """Stop the coordinator."""
        await self.coordinator.stop()
