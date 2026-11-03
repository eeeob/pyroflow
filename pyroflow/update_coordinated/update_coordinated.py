"""Abstract base for update types that are processed under coordination."""

from __future__ import annotations as _annotations

from abc import ABC
from typing import Any, TYPE_CHECKING

from pytrove import maybe_awaitable

from ..typings import UpdateType
from ..update_coordinator import UpdateCoordinator, MemoryUpdateCoordinator
from ..utils import UpdateBound, get_update_executor

if TYPE_CHECKING:
    from collections.abc import Callable

    from pytrove.typings import MaybeCoroutineCallable

    from ..typings import CoordinatedUpdateKeyT, CoordinatedUpdateIdT


class UpdateCoordinated(ABC, UpdateBound[UpdateType]):
    """Abstract policy that coordinates one update type.

    A subclass binds its update type through `__update_type__` and extracts two
    keys from each update:

    - `extract_key`: the lock that coordinates updates. Updates sharing a key
      wait for each other, across sessions when the backend is shared. Choose
      its level by passing `extract_key_func`: the chat, the chat and user, the
      message, or the update itself. `None` makes the update uncoordinated.
    - `extract_update_id`: the update's unique identity, used to mark it as
      handled. Extracted only once the key is known; never `None`.

    An update counts as handled, and its lock is released, as soon as a
    listener resolves it or one handler's filter passes it.

    Each callable may be sync or async; a sync one runs in a thread, on the
    client's executor when it has one.

    Args:
        coordinator_factory: Builds the `UpdateCoordinator` from the update
            type. Defaults to `MemoryUpdateCoordinator`.
        extract_key_func: `(update) -> key | None` backing `extract_key`. If
            `None`, a subclass must override that method.
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
        extract_key_func: MaybeCoroutineCallable[[UpdateType], CoordinatedUpdateKeyT | None]
        | None = None,
        extract_update_id_func: MaybeCoroutineCallable[[UpdateType], CoordinatedUpdateIdT]
        | None = None,
        **kw: Any,
    ) -> None:
        """Initialise the policy; see the class docstring for the parameters."""
        super().__init__(**kw)

        if coordinator_factory is None:
            coordinator_factory = MemoryUpdateCoordinator

        self.coordinator = coordinator_factory(self.__class__.__update_type__)
        """Backend that locks keys and remembers handled updates."""

        self.extract_key_func = extract_key_func
        """Callable returning an update's lock key, or `None` to use an override."""
        self.extract_update_id_func = extract_update_id_func
        """Callable returning an update's identity, or `None` to use an override."""

    async def extract_key(self, update: UpdateType) -> CoordinatedUpdateKeyT | None:
        """Return the lock key that coordinates `update`, or `None` to leave it uncoordinated.

        Updates with the same key are processed one at a time. This is not the
        update's identity; see `extract_update_id`.

        Args:
            update: The incoming update.

        Returns:
            The key naming the lock, or `None` if the update is not coordinated.

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
            executor=get_update_executor(update),
            log_exc=False,
        )

    async def extract_update_id(self, update: UpdateType) -> CoordinatedUpdateIdT:
        """Return the unique identity of `update`, used to mark it as handled.

        It must be extractable from the update every time, with the same value
        for the same update and a different one for any other: a shared
        identity drops every later update as already handled.

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
            executor=get_update_executor(update),
            log_exc=False,
        )

    async def start(self) -> None:
        """Start the coordinator."""
        await self.coordinator.start()

    async def stop(self) -> None:
        """Stop the coordinator."""
        await self.coordinator.stop()


__all__ = ("UpdateCoordinated",)
