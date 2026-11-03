"""Abstract base for update types whose handlers are recorded in a history."""

from __future__ import annotations as _annotations

from abc import ABC
from typing import Any, TYPE_CHECKING

from pytrove import maybe_awaitable

from ..typings import UpdateType
from ..update_history_store import UpdateHistoryStore, MemoryUpdateHistoryStore
from ..utils import UpdateBound, get_update_executor

if TYPE_CHECKING:
    from collections.abc import Callable

    from pytrove.typings import MaybeCoroutineCallable

    from ..typings import UpdateHistoryKeyT


class UpdateHistory(ABC, UpdateBound[UpdateType]):
    """Abstract policy that records which handlers processed each update of one type.

    A subclass binds its update type through `__update_type__` and extracts two
    values from each update:

    - `extract_key`: the key the update's records are stored under. `None`
      leaves the update unrecorded.
    - `extract_data`: the data stored with each record. Extracted only once
      the key is known.

    The dispatcher writes the handlers that succeeded to `store`; read them
    back with `store.get(key)`. The store owns TTL and capacity.

    Each callable may be sync or async; a sync one runs in a thread, on the
    client's executor when it has one.

    Args:
        store_factory: Builds the `UpdateHistoryStore` from the update type.
            Defaults to `MemoryUpdateHistoryStore`.
        extract_key_func: `(update) -> key | None` backing `extract_key`. If
            `None`, a subclass must override that method.
        extract_data_func: `(update) -> Any` backing `extract_data`. If
            `None`, a subclass must override that method.
        **kw: Passed to the next class in the MRO.

    Example:
        >>> import asyncio
        >>> from pyrogram.types import Chat, Message
        >>> from pyroflow.models import HandlerRef, UpdateRecord
        >>> class TextHistory(UpdateHistory[Message]):
        ...     __update_type__ = Message
        >>> history = TextHistory(
        ...     extract_key_func=lambda m: (m.chat.id,) if m.text is not None else None,
        ...     extract_data_func=lambda m: m.text,
        ... )
        >>> async def main():
        ...     message = Message(id=1, chat=Chat(id=5), text="hi")
        ...     key = await history.extract_key(message)
        ...     data = await history.extract_data(message)
        ...     handler = HandlerRef("pkg.handlers:Handler", "bot.handlers:start")
        ...     await history.store.update(key, UpdateRecord(handler=handler, data=data))
        ...     return key, [(r.handler.callback, r.data) for r in await history.store.get(key)]
        >>> asyncio.run(main())
        ((5,), [('bot.handlers:start', 'hi')])
    """

    def __init__(
        self,
        store_factory: Callable[[type[UpdateType]], UpdateHistoryStore] | None = None,
        extract_key_func: MaybeCoroutineCallable[[UpdateType], UpdateHistoryKeyT | None]
        | None = None,
        extract_data_func: MaybeCoroutineCallable[[UpdateType], Any] | None = None,
        **kw: Any,
    ) -> None:
        """Initialise the policy; see the class docstring for the parameters."""
        super().__init__(**kw)

        if store_factory is None:
            store_factory = MemoryUpdateHistoryStore

        self.store = store_factory(self.__class__.__update_type__)
        """Backend that holds the records."""

        self.extract_key_func = extract_key_func
        """Callable returning an update's history key, or `None` to use an override."""
        self.extract_data_func = extract_data_func
        """Callable returning an update's record data, or `None` to use an override."""

    async def extract_key(self, update: UpdateType) -> UpdateHistoryKeyT | None:
        """Return the key `update`'s records are stored under, or `None` to leave it unrecorded.

        Args:
            update: The incoming update.

        Returns:
            The history key, or `None` if the update is not recorded.

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

    async def extract_data(self, update: UpdateType) -> Any:
        """Return the data stored with each record of `update`.

        Args:
            update: The incoming update.

        Returns:
            The data attached to the records.

        Raises:
            NotImplementedError: If the method is not overridden and no
                `extract_data_func` was passed.
            TypeError: If `update` is not an instance of `__update_type__`.
        """
        if self.extract_data_func is None:
            msg = (
                f"{self.__class__.__name__} must either pass extract_data_func "
                f"or override extract_data()"
            )
            raise NotImplementedError(msg)

        self.validate_update(update)

        return await maybe_awaitable(
            self.extract_data_func,
            update,
            executor=get_update_executor(update),
            log_exc=False,
        )

    async def start(self) -> None:
        """Start the store."""
        await self.store.start()

    async def stop(self) -> None:
        """Stop the store."""
        await self.store.stop()


__all__ = ("UpdateHistory",)
