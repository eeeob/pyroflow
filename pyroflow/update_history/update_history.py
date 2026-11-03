"""Abstract base class for recording which handlers processed an update."""

from __future__ import annotations as _annotations

import time
from abc import ABC
from typing import Any, cast, TYPE_CHECKING

from pyrogram.types import Update as PyroUpdate
from pytrove import maybe_awaitable

from ..models import UpdateRecord
from ..typings import UpdateType
from ..update_history_store import UpdateHistoryStore, MemoryUpdateHistoryStore
from ..utils import UpdateBound, get_update_executor

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

    from pyrogram.handlers import Handler as PyroHandler
    from pytrove.typings import MaybeCoroutineCallable

    from ..typings import UpdateHistoryKeyT


class UpdateHistory(ABC, UpdateBound[UpdateType]):
    """Record which handlers processed each update of one Pyrogram type.

    A subclass binds the update type with `__update_type__`. Each of
    `is_recordable`, `extract_key` and `extract_data` comes either from the
    matching `*_func` argument or from an override; the store owns TTL and
    capacity. Sync callables run in a thread, on the executor of the update's
    client when it has one.

    Args:
        store_factory: Called with the update type to build the store;
            `MemoryUpdateHistoryStore` when `None`.
        is_recordable_func: `(update) -> bool`, sync or async, used by `is_recordable`.
        extract_key_func: `(update) -> UpdateHistoryKeyT`, sync or async, used by
            `extract_key`.
        extract_data_func: `(update) -> Any`, sync or async, used by `extract_data`.
        **kw: Passed to the next class in the MRO.

    Example:
        >>> import asyncio
        >>> from pyrogram.types import Chat, Message
        >>> class TextHistory(UpdateHistory[Message]):
        ...     __update_type__ = Message
        >>> history = TextHistory(
        ...     is_recordable_func=lambda m: m.text is not None,
        ...     extract_key_func=lambda m: (m.chat.id,),
        ...     extract_data_func=lambda m: m.text,
        ... )
        >>> async def main():
        ...     await history.record(Message(id=1, chat=Chat(id=5), text="hi"), "start")
        ...     await history.record(Message(id=2, chat=Chat(id=5)), "photo")
        ...     return [(r.handler, r.data) for r in await history.get((5,))]
        >>> asyncio.run(main())
        [('start', 'hi')]
    """

    def __init__(
        self,
        store_factory: Callable[[type[UpdateType]], UpdateHistoryStore] | None = None,
        is_recordable_func: MaybeCoroutineCallable[[UpdateType], bool] | None = None,
        extract_key_func: MaybeCoroutineCallable[[UpdateType], UpdateHistoryKeyT] | None = None,
        extract_data_func: MaybeCoroutineCallable[[UpdateType], Any] | None = None,
        **kw: Any,
    ) -> None:
        """Initialise the history and create its store."""
        super().__init__(**kw)

        if store_factory is None:
            store_factory = MemoryUpdateHistoryStore

        self.store = store_factory(self.__class__.__update_type__)
        """Backend that holds the records."""

        self.is_recordable_func = is_recordable_func
        """Callable behind `is_recordable`, or `None` when the method is overridden."""
        self.extract_key_func = extract_key_func
        """Callable behind `extract_key`, or `None` when the method is overridden."""
        self.extract_data_func = extract_data_func
        """Callable behind `extract_data`, or `None` when the method is overridden."""

    async def is_recordable(self, update: UpdateType) -> bool:
        """Return whether the update should be recorded; checked before any key or store access.

        Args:
            update: The incoming update.

        Returns:
            `True` to record the update, `False` to skip it.

        Raises:
            NotImplementedError: If no `is_recordable_func` was passed and the
                method is not overridden.
            TypeError: If `update` is not of the bound update type.
        """
        if self.is_recordable_func is None:
            msg = (
                f"{self.__class__.__name__} must either pass is_recordable_func "
                f"or override is_recordable()"
            )
            raise NotImplementedError(msg)

        self.validate_update(update)

        return await maybe_awaitable(  # ty: ignore[invalid-return-type]  # `pytrove` overloads cannot resolve `MaybeCoroutineCallable[..., T]` to `T`
            self.is_recordable_func, update, executor=get_update_executor(update), log_exc=False
        )

    async def extract_key(self, update: UpdateType) -> UpdateHistoryKeyT:
        """Return the store key of a recordable update.

        Args:
            update: The incoming update.

        Returns:
            The key its records are stored under.

        Raises:
            NotImplementedError: If no `extract_key_func` was passed and the
                method is not overridden.
            TypeError: If `update` is not of the bound update type.
        """
        if self.extract_key_func is None:
            msg = (
                f"{self.__class__.__name__} must either pass extract_key_func "
                f"or override extract_key()"
            )
            raise NotImplementedError(msg)

        self.validate_update(update)

        return await maybe_awaitable(  # ty: ignore[invalid-return-type]  # `pytrove` overloads cannot resolve `MaybeCoroutineCallable[..., T]` to `T`
            self.extract_key_func, update, executor=get_update_executor(update), log_exc=False
        )

    async def extract_data(self, update: UpdateType) -> Any:
        """Return the data stored with each record of a recordable update.

        Args:
            update: The incoming update.

        Returns:
            The data attached to the records.

        Raises:
            NotImplementedError: If no `extract_data_func` was passed and the
                method is not overridden.
            TypeError: If `update` is not of the bound update type.
        """
        if self.extract_data_func is None:
            msg = (
                f"{self.__class__.__name__} must either pass extract_data_func "
                f"or override extract_data()"
            )
            raise NotImplementedError(msg)

        self.validate_update(update)

        return await maybe_awaitable(
            self.extract_data_func, update, executor=get_update_executor(update), log_exc=False
        )

    async def record(self, update: UpdateType, handler: PyroHandler, check: bool = True) -> None:
        """Record that `handler` processed `update`; does nothing if the update is not recordable.

        Args:
            update: The processed update.
            handler: The handler that processed it.
            check: Whether to call `is_recordable` first; pass `False` when the
                caller already checked it.
        """
        if check:
            if not await self.is_recordable(update):
                return

        key = await self.extract_key(update)
        data = await self.extract_data(update)

        await self.store.update(key, UpdateRecord(handler=handler, data=data))

    async def record_many(
        self, update: UpdateType, handlers: Sequence[PyroHandler], check: bool = True
    ) -> None:
        """Record several handlers for `update` in one store write, sharing one timestamp.

        Does nothing if the update is not recordable.

        Args:
            update: The processed update.
            handlers: The handlers to record, in invocation order.
            check: Whether to call `is_recordable` first; pass `False` when the
                caller already checked it.
        """
        if check:
            if not await self.is_recordable(update):
                return

        key = await self.extract_key(update)
        data = await self.extract_data(update)

        now = time.time()

        records = [UpdateRecord(handler=handler, data=data, created_at=now) for handler in handlers]

        await self.store.update(key, *records)

    async def get(self, update: UpdateType | UpdateHistoryKeyT) -> Sequence[UpdateRecord]:
        """Return the records stored for an update or a key.

        An update that is not recordable yields an empty sequence; a key skips
        that check.

        Args:
            update: An update, or a key to look up directly.

        Returns:
            The records, oldest first; empty if there are none.
        """
        if isinstance(update, PyroUpdate):
            # `ty` keeps a theoretical `tuple & Update` member; a real update lands here.
            update = cast("UpdateType", update)

            if not await self.is_recordable(update):
                return []

            key = await self.extract_key(update)
        else:
            key = update

        return await self.store.get(key)

    async def pop(self, update: UpdateType | UpdateHistoryKeyT) -> Sequence[UpdateRecord]:
        """Remove and return the records stored for an update or a key.

        An update that is not recordable yields an empty sequence and removes
        nothing; a key skips that check.

        Args:
            update: An update, or a key to look up directly.

        Returns:
            The removed records, oldest first; empty if there were none.
        """
        if isinstance(update, PyroUpdate):
            # `ty` keeps a theoretical `tuple & Update` member; a real update lands here.
            update = cast("UpdateType", update)

            if not await self.is_recordable(update):
                return []

            key = await self.extract_key(update)
        else:
            key = update

        return await self.store.pop(key)

    async def clear(self, update: UpdateType | UpdateHistoryKeyT) -> None:
        """Delete the records stored for an update or a key.

        An update that is not recordable deletes nothing; a key skips that check.

        Args:
            update: An update, or a key to delete directly.
        """
        if isinstance(update, PyroUpdate):
            # `ty` keeps a theoretical `tuple & Update` member; a real update lands here.
            update = cast("UpdateType", update)

            if not await self.is_recordable(update):
                return

            key = await self.extract_key(update)
        else:
            key = update

        await self.store.delete(key)

    async def start(self) -> None:
        """Start the history and its store."""
        await self.store.start()

    async def stop(self) -> None:
        """Stop the history and its store."""
        await self.store.stop()


__all__ = ("UpdateHistory",)
