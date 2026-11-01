"""Abstract base for update types that are processed under coordination."""

from __future__ import annotations as _annotations

import logging
from abc import ABC
from typing import Any, TYPE_CHECKING

from pytrove import maybe_awaitable

from ..typings import AsyncLockProto, UpdateType
from ..update_coordinator import UpdateCoordinator, MemoryUpdateCoordinator
from ..utils import UpdateBound

if TYPE_CHECKING:
    from collections.abc import Callable
    from concurrent.futures import ThreadPoolExecutor

    from pytrove.typings import MaybeCoroutineCallable

    from ..typings import UpdateCoordinatorKeyT

log = logging.getLogger(__name__)


class UpdateCoordinated(ABC, UpdateBound[UpdateType]):
    """Abstract policy that coordinates one update type.

    A subclass binds its update type through `__update_type__` and decides
    whether an update is coordinated, its lock scope (`extract_key`) and its
    identity (`extract_update_id`). Updates sharing a scope are processed one
    at a time, in arrival order; each identity is processed once. By default
    both are the update itself. Widen the scope to serialise a whole chat, but
    keep the identity unique: a shared identity drops every later update as a
    duplicate.

    Each callable may be sync or async; a sync one runs in a thread, on the
    client's executor when it has one.

    Args:
        coordinator_factory: Builds the `UpdateCoordinator` from the update
            type. Defaults to `MemoryUpdateCoordinator`.
        is_coordinatable_func: `(update) -> bool` backing `is_coordinatable`.
            If `None`, a subclass must override that method.
        extract_key_func: `(update) -> key` backing `extract_key`. If `None`,
            a subclass must override that method.
        extract_update_id_func: `(update) -> key` backing `extract_update_id`.
            If `None`, a subclass must override that method.
        **kw: Passed to the next class in the MRO.

    Example:
        >>> import asyncio
        >>> from pyroflow.types import CallbackQuery, User
        >>> from pyroflow.update_coordinated import CallbackQueryCoordinated
        >>> query = CallbackQuery(id="q1", from_user=User(id=7))
        >>> per_user = CallbackQueryCoordinated(extract_key_func=lambda q: (q.from_user.id,))
        >>> asyncio.run(per_user.extract_key(query)), asyncio.run(per_user.extract_update_id(query))
        ((7,), ('q1',))
    """

    def __init__(
        self,
        coordinator_factory: Callable[[type[UpdateType]], UpdateCoordinator] | None = None,
        is_coordinatable_func: MaybeCoroutineCallable[[UpdateType], bool] | None = None,
        extract_key_func: MaybeCoroutineCallable[[UpdateType], UpdateCoordinatorKeyT] | None = None,
        extract_update_id_func: MaybeCoroutineCallable[[UpdateType], UpdateCoordinatorKeyT]
        | None = None,
        **kw: Any,
    ) -> None:
        """Initialise the policy; see the class docstring for the parameters."""
        super().__init__(**kw)

        if coordinator_factory is None:
            coordinator_factory = MemoryUpdateCoordinator

        self.coordinator = coordinator_factory(self.__class__.__update_type__)

        self.is_coordinatable_func = is_coordinatable_func
        self.extract_key_func = extract_key_func
        self.extract_update_id_func = extract_update_id_func

    def _get_executor(self, update: UpdateType) -> ThreadPoolExecutor | None:
        """Return the executor of the client bound to `update`, or `None` if it has none."""
        return getattr(getattr(update, "_client", None), "executor", None)

    async def is_coordinatable(self, update: UpdateType) -> bool:
        """Return whether `update` is coordinated.

        An uncoordinated update is processed normally, with no lock and no
        registration.

        Args:
            update: The incoming update.

        Returns:
            `True` if the update is coordinated, `False` otherwise.

        Raises:
            NotImplementedError: If the method is not overridden and no
                `is_coordinatable_func` was passed.
            TypeError: If `update` is not an instance of `__update_type__`.
        """
        if self.is_coordinatable_func is None:
            msg = (
                f"{self.__class__.__name__} must either pass is_coordinatable_func "
                f"or override is_coordinatable()"
            )
            raise NotImplementedError(msg)

        self.validate_update(update)

        return await maybe_awaitable(  # ty: ignore[invalid-return-type]  # `pytrove` `maybe_awaitable` overloads resolve `MaybeCoroutineCallable[..., T]` to `T | Coroutine[T]`
            self.is_coordinatable_func,
            update,
            executor=self._get_executor(update),
        )

    async def extract_key(self, update: UpdateType) -> UpdateCoordinatorKeyT:
        """Return the lock scope of `update`.

        Updates with the same scope are processed one at a time, in arrival
        order. This is not the update's identity; see `extract_update_id`.

        Args:
            update: The incoming update.

        Returns:
            The key naming the scope to serialise.

        Raises:
            NotImplementedError: If the method is not overridden and no
                `extract_key_func` was passed.
            TypeError: If `update` is not an instance of `__update_type__`.
        """
        if self.extract_key_func is None:
            msg = (
                f"{self.__class__.__name__} must either pass extract_key_func "
                f"or override extract_key()"
            )
            raise NotImplementedError(msg)

        self.validate_update(update)

        return await maybe_awaitable(  # ty: ignore[invalid-return-type]  # `pytrove` `maybe_awaitable` overloads resolve `MaybeCoroutineCallable[..., T]` to `T | Coroutine[T]`
            self.extract_key_func,
            update,
            executor=self._get_executor(update),
        )

    async def extract_update_id(self, update: UpdateType) -> UpdateCoordinatorKeyT:
        """Return the identity of `update`, used for deduplication.

        It is checked before processing and registered once handled, so an
        update is processed once, across sessions when the backend is shared.
        It must stay unique per update: a shared identity drops every later
        update as an already handled duplicate.

        Args:
            update: The incoming update.

        Returns:
            The key identifying this update.

        Raises:
            NotImplementedError: If the method is not overridden and no
                `extract_update_id_func` was passed.
            TypeError: If `update` is not an instance of `__update_type__`.
        """
        if self.extract_update_id_func is None:
            msg = (
                f"{self.__class__.__name__} must either pass extract_update_id_func "
                f"or override extract_update_id()"
            )
            raise NotImplementedError(msg)

        self.validate_update(update)

        return await maybe_awaitable(  # ty: ignore[invalid-return-type]  # `pytrove` `maybe_awaitable` overloads resolve `MaybeCoroutineCallable[..., T]` to `T | Coroutine[T]`
            self.extract_update_id_func,
            update,
            executor=self._get_executor(update),
        )

    async def lock(self, update: UpdateType) -> AsyncLockProto:
        """Build the lock for the scope of `update`, unacquired.

        The caller decides when to acquire and release it; see
        `pyroflow.mark_handled`.

        Args:
            update: The incoming update.

        Returns:
            An async lock usable with `async with`.
        """
        return self.coordinator.lock(await self.extract_key(update))

    async def start(self) -> None:
        """Start the coordinator."""
        await self.coordinator.start()

    async def stop(self) -> None:
        """Stop the coordinator."""
        await self.coordinator.stop()


__all__ = ("UpdateCoordinated",)
