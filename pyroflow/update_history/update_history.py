from abc import ABC
from typing import Callable, Union, Sequence, Type, Optional, Any
from concurrent.futures import ThreadPoolExecutor

from pyrogram.handlers import Handler as PyroHandler
from pyrogram.types import Update as PyroUpdate

from ..utils import UpdateBound, maybe_awaitable
from ..utils.typings import UpdateType, MaybeCoroutineCallable

from ..typings import UpdateHistoryKeyT
from ..models import UpdateRecord
from ..update_history_store import UpdateHistoryStore, MemoryUpdateHistoryStore

import time


class UpdateHistory(ABC, UpdateBound[UpdateType]):
    """
    Abstract base for per-update-type handler history.

    Each subclass is bound to a single Pyrogram update type via
    ``__update_type__`` and defines how to extract a :data:`UpdateHistoryKeyT`
    from an incoming update. The store factory is responsible for all
    storage details (TTL, capacity, backend).

    The dispatcher records a :class:`UpdateRecord` after every
    successful handler invocation, allowing later handlers (e.g. a
    ``back`` handler) to replay or inspect previous processing.

    Each of the three core behaviours — recordability check, key extraction,
    and data extraction — can be provided either by overriding the
    corresponding method in a subclass, or by passing a callable at
    construction time via ``is_recordable_func``, ``extract_key_func``,
    or ``extract_data_func``.

    Parameters:
        store_factory: Optional callable that receives the update type and
                        returns a configured :class:`UpdateHistoryStore`
                        instance. If ``None``, a
                        :class:`MemoryUpdateHistoryStore` will be used.
        is_recordable_func: Optional callable ``(update) -> bool`` used by
                            :meth:`is_recordable`. If ``None``, the method
                            must be overridden in a subclass.
        extract_key_func:   Optional callable ``(update) -> UpdateHistoryKeyT``
                            used by :meth:`extract_key`. If ``None``, the method
                            must be overridden in a subclass.
        extract_data_func:  Optional callable ``(update) -> Any``
                            used by :meth:`extract_data`. If ``None``, the method
                            must be overridden in a subclass.
        **kw:               Passed to the next class in the MRO.
        
    """

    def __init__(
        self, 
        store_factory: Optional[Callable[[Type[UpdateType]], UpdateHistoryStore]] = None, 
        is_recordable_func: Optional[MaybeCoroutineCallable[[UpdateType], bool]] = None, 
        extract_key_func: Optional[MaybeCoroutineCallable[[UpdateType], UpdateHistoryKeyT]] = None, 
        extract_data_func: Optional[MaybeCoroutineCallable[[UpdateType], Any]] = None, 
        **kw, 
    ) -> None:
        
        super().__init__(**kw)
        
        if store_factory is None:
            store_factory = MemoryUpdateHistoryStore
        
        self.store = store_factory(self.__class__.__update_type__)

        self.is_recordable_func = is_recordable_func
        self.extract_key_func = extract_key_func
        self.extract_data_func = extract_data_func

        
    def _get_executor(self, update: UpdateType) -> Optional[ThreadPoolExecutor]:
        return getattr(
            getattr(update, "_client", None), 
            "executor", 
            None
        )


    async def is_recordable(self, update: UpdateType) -> bool:
        """
        Determine whether this update should be recorded.

        Called before any key extraction or storage operation.
        Return ``False`` to skip recording entirely for this update.

        Parameters:
            update: The incoming Pyrogram update.

        Returns:
            ``True`` if the update should be recorded, ``False`` otherwise.
        """
        
        if self.is_recordable_func is None:
            raise NotImplementedError(
                f"{self.__class__.__name__} must either pass is_recordable_func "
                f"or override is_recordable()"
            )

        self.validate_update(update)

        return await maybe_awaitable(
            self.is_recordable_func, 
            update, 
            executor=self._get_executor(update)
        )

    async def extract_key(self, update: UpdateType) -> UpdateHistoryKeyT:
        """
        Extract a storage key from the update.

        Only called when :meth:`is_recordable` returns ``True``.

        Parameters:
            update: The incoming Pyrogram update.

        Returns:
            A :data:`UpdateHistoryKeyT` that uniquely identifies the
            (chat, user) context.
        """

        if self.extract_key_func is None:
            raise NotImplementedError(
                f"{self.__class__.__name__} must either pass extract_key_func "
                f"or override extract_key()"
            )

        self.validate_update(update)

        return await maybe_awaitable(
            self.extract_key_func, 
            update, 
            executor=self._get_executor(update)
        )

    async def extract_data(self, update: UpdateType) -> Any:
        """
        Extract relevant data from the update to attach to each record.

        Only called when :meth:`is_recordable` returns ``True``.

        Parameters:
            update: The incoming Pyrogram update.

        Returns:
            Any data worth storing alongside the handler record.
        """

        if self.extract_data_func is None:
            raise NotImplementedError(
                f"{self.__class__.__name__} must either pass extract_data_func "
                f"or override extract_data()"
            )

        self.validate_update(update)

        return await maybe_awaitable(
            self.extract_data_func, 
            update, 
            executor=self._get_executor(update)
        )

    async def record(self, update: UpdateType, handler: PyroHandler, check: bool = True) -> None:
        """
        Record a single successful handler invocation for the given update.

        Silently skips if :meth:`is_recordable` returns ``False``.

        Parameters:
            update:  The update that was processed.
            handler: The handler that processed it.
            check:   If ``True``, calls :meth:`is_recordable` before recording.
                    Pass ``False`` to skip the check when the caller has
                    already verified recordability.
        """

        if check:
            if not await self.is_recordable(update):
                return

        key = await self.extract_key(update)
        data = await self.extract_data(update)

        await self.store.update(key, UpdateRecord(handler=handler, data=data))

    async def record_many(self, update: UpdateType, handlers: Sequence[PyroHandler], check: bool = True) -> None:
        """
        Record multiple handler invocations for the given update at once.

        Silently skips if :meth:`is_recordable` returns ``False``.

        Parameters:
            update:   The update that was processed.
            handlers: The handlers to record, in invocation order.
            check:    If ``True``, calls :meth:`is_recordable` before recording.
                    Pass ``False`` to skip the check when the caller has
                    already verified recordability.
        """

        if check:
            if not await self.is_recordable(update):
                return

        key = await self.extract_key(update)
        data = await self.extract_data(update)

        now = time.time()

        records = [
            UpdateRecord(handler=handler, data=data, created_at=now)
            for handler in handlers
        ]

        await self.store.update(key, *records)

    async def get(self, update: Union[UpdateType, UpdateHistoryKeyT]) -> Sequence[UpdateRecord]:
        """
        Retrieve all recorded handlers for the given update or key.

        If a :class:`PyroUpdate` is passed, :meth:`is_recordable` is called
        first and an empty sequence is returned if it yields ``False``.
        If a :data:`UpdateHistoryKeyT` is passed directly, the check
        is skipped.

        Parameters:
            update: The incoming Pyrogram update or a raw
                    :data:`UpdateHistoryKeyT` to look up directly.

        Returns:
            A sequence of :class:`UpdateRecord` ordered from oldest
            to newest, or an empty sequence if none exist.
        """

        key = update

        if isinstance(key, PyroUpdate):
            if not await self.is_recordable(update):
                return []
            
            key = await self.extract_key(update)

        return await self.store.get(key)
    
    async def pop(self, update: Union[UpdateType, UpdateHistoryKeyT]) -> Sequence[UpdateRecord]:
        """
        Remove and Retrieve all recorded handlers for the given update or key.

        If a :class:`PyroUpdate` is passed, :meth:`is_recordable` is called
        first and an empty sequence is returned if it yields ``False``.
        If a :data:`UpdateHistoryKeyT` is passed directly, the check
        is skipped.

        Parameters:
            update: The incoming Pyrogram update or a raw
                    :data:`UpdateHistoryKeyT` to look up directly.

        Returns:
            A sequence of :class:`UpdateRecord` ordered from oldest
            to newest, or an empty sequence if none exist.
        """

        key = update

        if isinstance(key, PyroUpdate):
            if not await self.is_recordable(update):
                return []
            
            key = await self.extract_key(update)

        return await self.store.pop(key)

    async def clear(self, update: Union[UpdateType, UpdateHistoryKeyT]) -> None:
        """
        Delete all records for the given update or key.

        If a :class:`PyroUpdate` is passed, :meth:`is_recordable` is called
        first and the operation is skipped if it yields ``False``.
        If a :data:`UpdateHistoryKeyT` is passed directly, the check
        is skipped.

        Parameters:
            update: The incoming Pyrogram update or a raw
                    :data:`UpdateHistoryKeyT` to delete directly.
        """

        key = update

        if isinstance(key, PyroUpdate):
            if not await self.is_recordable(update):
                return
            
            key = await self.extract_key(update)

        await self.store.delete(key)

    async def start(self) -> None:
        """Start the history and its store."""
        await self.store.start()

    async def stop(self) -> None:
        """Stop the history and its store."""
        await self.store.stop()
