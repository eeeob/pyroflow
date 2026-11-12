"""Base class for per-update-type listeners that back the `ask_*` methods and `listen`."""

from __future__ import annotations as _annotations

import asyncio
import logging
from abc import ABC
from typing import Any, TYPE_CHECKING, TypedDict

from ..typings import UpdateType
from ..dispatcher.dispatcher import _HANDLER_WORKER, _HANDLER_HOLD
from ..utils import UpdateBound, call_maybe_async, get_update_executor
from ..errors import (
    ListenerAlreadyExists,
    ListenerCancelled,
    ListenerError,
    ListenerEvicted,
    ListenerRejected,
    ListenerReplaced,
    ListenerTimeout,
)
from ..enums import DuplicatePolicy, ListenerScope
from ..models import ListenerModel

if TYPE_CHECKING:
    from collections.abc import Callable

    from pyrogram.filters import Filter
    from pytrove.typings import MaybeCoroutineCallable, Number

    from ..models import ListenerContext, ListenerKey


log = logging.getLogger(__name__)
"""Logger for errors of listener filters and `on_error_func`."""


class ListenKw(TypedDict, total=False):
    """The arguments of a wait that every `listen` accepts besides its key."""

    context: ListenerContext | None
    """Values attached to the wait; `None` attaches none."""
    filters: Filter | None
    """A Pyrogram filter the update must pass besides its key."""
    strict: bool
    """Whether an update that matches the key but fails `filters` ends the wait."""
    timeout: Number | None
    """Seconds to wait; `None` falls back to the listener's own `timeout`."""


class UpdateListener(ABC, UpdateBound[UpdateType]):
    """Abstract base that waits for updates of one Pyrogram type, keyed by a `ListenerKey` class.

    A subclass binds the update type with `__update_type__` and the key class
    with `__key_type__`. Updates are keyed by `from_update` of the key class,
    unless `extract_key_func` is given or `extract_key` is overridden; a key
    of `None` skips the update.

    Every waiting listener lives in this process: an update is matched only
    against the listeners of the client that received it.

    A `listen` can also carry a Pyrogram filter. An update whose key matches
    but that fails the filter is skipped, and the listener keeps waiting; with
    `strict`, it ends the wait with `ListenerRejected` instead. See `listen`
    for the waits this can leave open.

    Args:
        duplicate_policy: What `listen` does when the key already has a
            waiting listener; `DuplicatePolicy.REPLACE` if `None`.
        extract_key_func: `(update) -> key | None`, sync, used by
            `extract_key`; `None` skips the update. It runs inline on the
            event loop, so it must be fast. `None` uses `from_update` of
            `__key_type__`.
        on_error_func: `(exc, listener_model) -> object`, sync or async,
            called when a `ListenerError` ends a wait (a timeout, a
            cancellation, an eviction or a strict rejection), after the wait
            is removed and before `listen` raises the error. Errors raised
            before a wait starts, `ListenerAlreadyExists` and
            `ListenerWorkersBusy`, are not reported. A failing callback is
            logged and never hides the error.
        timeout: Default seconds `listen` waits; `None` waits indefinitely.
        resolve_scope: Which matching waits `resolve` gives an update to:
            `ListenerScope.FIRST` the first in priority order,
            `ListenerScope.ALL` every one.
        strict_filter: Pyrogram filter for a `listen` that passes no
            `filters`; an update that fails it ends the wait, as with `strict`.
        **kw: Passed to the next class in the MRO.

    Example:
        >>> from pyrogram.types import Chat, Message
        >>> from pyroflow.models import MessageKey
        >>> class ChatListener(UpdateListener[Message]):
        ...     __update_type__ = Message
        ...     __key_type__ = MessageKey
        >>> async def main():
        ...     listener = ChatListener(
        ...         extract_key_func=lambda update: MessageKey(update.chat.id),
        ...     )
        ...     waiter = asyncio.create_task(listener.listen(MessageKey(1)))
        ...     await asyncio.sleep(0)
        ...     resolved = await listener.resolve(Message(id=7, chat=Chat(id=1)))
        ...     return resolved, (await waiter).id
        >>> asyncio.run(main())
        (True, 7)
    """

    __key_type__: type[ListenerKey[UpdateType]]
    """The `ListenerKey` class the waits of this listener are keyed by."""

    def __init__(
        self,
        duplicate_policy: DuplicatePolicy | None = None,
        extract_key_func: Callable[[UpdateType], ListenerKey[UpdateType] | None] | None = None,
        on_error_func: MaybeCoroutineCallable[[ListenerError, ListenerModel], object] | None = None,
        timeout: Number | None = None,
        resolve_scope: ListenerScope = ListenerScope.FIRST,
        strict_filter: Filter | None = None,
        **kw: object,
    ) -> None:
        """Initialise the listener; see the class docstring for the parameters."""
        super().__init__(**kw)

        if duplicate_policy is None:
            duplicate_policy = DuplicatePolicy.REPLACE

        self.duplicate_policy = duplicate_policy
        """What `listen` does when the key already has a waiting listener."""

        if extract_key_func is None:
            extract_key_func = self.__key_type__.from_update

        self.extract_key_func = extract_key_func
        """The key extractor behind `extract_key`."""
        self.on_error_func = on_error_func
        """Optional callback for the `ListenerError` that ends a wait."""

        self.timeout = timeout
        """Default seconds `listen` waits; `None` waits indefinitely."""
        self.resolve_scope = resolve_scope
        """Which matching waits `resolve` gives an update to."""
        self.strict_filter = strict_filter
        """Filter for a `listen` that passes no `filters`; an update that fails it ends the wait."""

        self.listeners: dict[ListenerKey[UpdateType], ListenerModel[UpdateType]] = {}
        """Waiting listeners, by key; changed only through `_add` and `_remove`."""
        self.is_closed = False
        """Whether `stop` ran since the last `start`; `listen` refuses to wait while it is."""

        key_fields = self.__key_type__.key_fields
        self._exact_mask = sum(
            1 << key_fields.index(name) for name in self.__key_type__.exact_fields
        )
        """The bits of the key fields marked `exact`, in `key_fields` order."""
        self._shapes: dict[int, int] = {}
        """How many waits are registered with each shape, a bitmask of the fields their key sets."""
        self._shape_order: tuple[int, ...] = ()
        """The shapes of `_shapes` in the order `resolve` tries them."""

    def _shape_of(self, values: tuple[object, ...]) -> int:
        """Return the shape of a key's values: a bitmask of those set, `exact` fields aside.

        Args:
            values: The key's values, as `ListenerKey.to_tuple` returns them.

        Returns:
            Bit `i` set for each field `i` that is not `None` and not `exact`.
        """
        shape = 0

        for bit, value in enumerate(values):
            if value is not None:
                shape |= 1 << bit

        return shape & ~self._exact_mask

    def _order_shapes(self) -> None:
        """Sort `_shapes` into `_shape_order`: more fields first, then by field order."""
        fields = range(len(self.__key_type__.key_fields))

        self._shape_order = tuple(
            sorted(
                self._shapes,
                key=lambda shape: (-shape.bit_count(), tuple(b for b in fields if shape >> b & 1)),
            )
        )

    def _add(self, model: ListenerModel[UpdateType]) -> None:
        """Register `model` under its key, in place of any model there, and count its shape.

        Args:
            model: The wait to register.
        """
        self._remove(model.key)
        self.listeners[model.key] = model

        shape = self._shape_of(model.key.to_tuple())
        count = self._shapes.get(shape, 0)
        self._shapes[shape] = count + 1

        if not count:
            self._order_shapes()

    def _remove(self, key: ListenerKey[UpdateType]) -> ListenerModel[UpdateType] | None:
        """Unregister the model under `key`, and uncount its shape.

        Args:
            key: The key the model is registered under.

        Returns:
            The removed model, or `None` if none was registered.
        """
        model = self.listeners.pop(key, None)

        if model is not None:
            shape = self._shape_of(key.to_tuple())

            if count := self._shapes[shape] - 1:
                self._shapes[shape] = count
            else:
                del self._shapes[shape]
                self._order_shapes()

        return model

    def _cleanup_model(self, model: ListenerModel[UpdateType]) -> None:
        """Remove `model` from `listeners`, unless a newer wait took its key."""
        if self.listeners.get(model.key) is model:
            self._remove(model.key)

    def _time_out(self, listener: ListenerModel[UpdateType]) -> None:
        """End `listener` with `ListenerTimeout`, unless it is done already.

        Its timer may be due in the same loop iteration something else ended it.

        Args:
            listener: The wait whose `timeout` expired.
        """
        if not listener.done():
            listener.set_exc(ListenerTimeout(listener.key))

    async def start(self) -> None:
        """Accept `listen` calls again after a `stop`."""
        self.is_closed = False

    async def stop(self) -> None:
        """Refuse new `listen` calls and cancel every waiting listener."""
        self.is_closed = True

        for key in list(self.listeners):
            self.cancel(key)

    def cancel(self, key: ListenerKey[UpdateType]) -> bool:
        """Cancel the listener waiting on `key`; its waiter gets `ListenerCancelled`.

        Args:
            key: The key identifying the listener.

        Returns:
            Whether a listener was cancelled.

        Example:
            >>> from pyroflow.models import MessageKey
            >>> from pyroflow.update_listener import MessageListener
            >>> async def main():
            ...     listener = MessageListener()
            ...     waiter = asyncio.create_task(listener.listen(MessageKey(1)))
            ...     await asyncio.sleep(0)
            ...     cancelled = listener.cancel(MessageKey(1))
            ...     try:
            ...         await waiter
            ...     except ListenerCancelled:
            ...         return cancelled
            >>> asyncio.run(main())
            True
        """
        listener = self._remove(key)

        if listener is None:
            return False

        if not listener.done():
            listener.set_exc(ListenerCancelled(key))

        return True

    def evict(
        self,
        key: ListenerKey[UpdateType],
        *,
        model: ListenerModel[UpdateType] | None = None,
    ) -> bool:
        """End the listener waiting on `key` to free the worker its handler holds.

        Its waiter gets `ListenerEvicted`, a `ListenerCancelled`. Used by
        `WorkersPolicy.CANCEL_OLDEST`.

        Args:
            key: The key identifying the listener.
            model: Evict only this registered wait, not a newer one on the
                same key; `None` evicts whichever waits.

        Returns:
            Whether a listener was evicted.
        """
        listener = self.listeners.get(key)

        if listener is None or (model is not None and listener is not model):
            return False

        self._remove(key)

        if not listener.done():
            listener.set_exc(ListenerEvicted(key))

        return True

    def reject(self, key: ListenerKey[UpdateType]) -> bool:
        """End the listener waiting on `key` because an update failed its filter.

        Its waiter gets `ListenerRejected`.

        Args:
            key: The key identifying the listener.

        Returns:
            Whether a listener was rejected.

        Example:
            >>> from pyroflow.models import MessageKey
            >>> from pyroflow.update_listener import MessageListener
            >>> async def main():
            ...     listener = MessageListener()
            ...     waiter = asyncio.create_task(listener.listen(MessageKey(1)))
            ...     await asyncio.sleep(0)
            ...     rejected = listener.reject(MessageKey(1))
            ...     try:
            ...         await waiter
            ...     except ListenerRejected:
            ...         return rejected
            >>> asyncio.run(main())
            True
        """
        listener = self._remove(key)

        if listener is None:
            return False

        if not listener.done():
            listener.set_exc(ListenerRejected(key))

        return True

    async def listen(
        self,
        key: ListenerKey[UpdateType],
        *,
        context: ListenerContext | None = None,
        filters: Filter | None = None,
        strict: bool = False,
        timeout: Number | None = None,
    ) -> UpdateType:
        """Wait for the next update matching `key`.

        The listener is registered before this coroutine first yields, so it
        takes the first matching update the dispatcher handles after the
        call. Also callable as `listener(...)`.

        Inside a handler, the wait holds the worker running it, so the
        client's `WorkersPolicy` applies first (see
        `Client.setup_pyroflow`).

        Args:
            key: The key to wait on, a `__key_type__`; a `None` field matches
                any value.
            context: Values attached to the listener model; `None` attaches none.
            filters: A Pyrogram filter the update must pass besides its key;
                `None` falls back to the listener's `strict_filter`.
            strict: What an update whose key matches but that fails `filters`
                does: `True` ends the wait with `ListenerRejected`, `False`
                skips the update and keeps waiting.
            timeout: Seconds to wait; `None` falls back to the listener's own
                `timeout`, and waits indefinitely when that is `None` too.

        Returns:
            The matching Pyrogram update.

        Raises:
            TypeError: If `key` is not exactly a `__key_type__`; a subclass
                key would never match the lookups `resolve` builds.
            ListenerAlreadyExists: If a listener already waits on the key and
                `duplicate_policy` is `DuplicatePolicy.REJECT`.
            ListenerTimeout: If the timeout expires before the update arrives.
            ListenerCancelled: If the listener is stopped, or is cancelled while
                waiting, including when a newer listener replaces it.
            ListenerRejected: If `strict` is true, or `strict_filter` applies,
                and an update whose key matches fails the filter.
            ListenerEvicted: If `WorkersPolicy.CANCEL_OLDEST` ended this
                wait inside a handler to give its place to a newer one.
            ListenerWorkersBusy: If the wait would start inside a handler
                with no worker to spare, under `WorkersPolicy.REJECT`, or
                under `WorkersPolicy.CANCEL_OLDEST` with no wait to end.

        Warning:
            A wait that is not `strict` can stay open for good, until
            `timeout` or forever without one, when every update its key can
            still match fails `filters`:

            - The filter cannot pass this update type at all, such as a
              photo filter on a `CallbackQueryListener`.
            - The user keeps sending updates the filter rejects.

            Bound such waits with `timeout` (here or on the listener), pass
            `strict=True` when the first rejected update should end the wait,
            or end it with `cancel`. `strict=True` ends the wait on any
            rejected update of the key, such as a photo while text is
            awaited; catch `ListenerRejected` to ask again.

            `WorkersPolicy` counts a wait only in the worker's own task, so
            not one in a sync handler, in `asyncio.gather`, or in
            `asyncio.wait_for` before Python 3.12, though the worker waits
            for it. Bound such waits with `timeout`.

            Under a `CoordinatedDispatcher`, a wait inside a coordinated
            handler, or in a task or `asyncio.to_thread` it started, is
            offered the updates queued for the handler's key, in order, from
            the moment it starts.

        Example:
            >>> from pyroflow.models import MessageKey
            >>> from pyroflow.update_listener import MessageListener
            >>> async def main():
            ...     try:
            ...         await MessageListener().listen(MessageKey(1), timeout=0.01)
            ...     except ListenerTimeout as e:
            ...         return e.value
            >>> asyncio.run(main())
            MessageKey(chat_id=1, user_id=None, message_thread_id=None, direct_messages_topic_id=None, ephemeral=False)
        """
        if type(key) is not self.__key_type__:
            msg = (
                f"{self.__class__.__name__}.listen needs exactly a {self.__key_type__.__name__}, "
                f"not {type(key).__name__}"
            )
            raise TypeError(msg)

        # Read here alone, with no `current_task` check: a wait in a sync handler or a spawned task counts.
        hold = _HANDLER_HOLD.get()

        # A wait of a coordinated handler starts between two offers of its lane, never during
        # one; once the handler ended there is nothing to wait for. Nothing below suspends
        # before the wait is registered, so the lock is not kept.
        if hold is not None:
            await hold[1].wait_offer_lock(handler_active_required=True)

        if self.is_closed:
            raise ListenerCancelled(key)

        current = self.listeners.get(key)

        # A finished listener whose `listen` has not returned yet is no longer waiting.
        if current is not None and current.done():
            current = None

        if current is not None and self.duplicate_policy is DuplicatePolicy.REJECT:
            raise ListenerAlreadyExists(key)

        if filters is None and self.strict_filter is not None:
            filters, strict = self.strict_filter, True

        dispatcher = None
        holder = _HANDLER_WORKER.get()

        # Only a wait in the worker task itself is counted, not one in a task the handler spawned.
        if (
            holder is not None
            and (policy := holder[0].client.workers_policy) is not None
            and asyncio.current_task() is holder[1]
        ):
            dispatcher = holder[0]

            # A wait replacing one that holds a slot takes that slot, so it needs no check.
            if current not in dispatcher.listener_waits:
                dispatcher.enter_handler_wait(policy, key)

        if current is not None:
            current.set_exc(ListenerReplaced(key))

        listener = ListenerModel(
            key,
            future := asyncio.get_running_loop().create_future(),
            context,
            filters=filters,
            strict=strict,
        )
        self._add(listener)

        listener.add_done_callback(self._cleanup_model)

        if dispatcher is not None:
            # The slot frees the moment the wait ends, not when this coroutine resumes.
            listener.add_done_callback(dispatcher.end_handler_wait)
            dispatcher.listener_waits[listener] = self

        if timeout is None:
            timeout = self.timeout

        timer = (
            asyncio.get_running_loop().call_later(timeout, self._time_out, listener)
            if timeout is not None
            else None
        )
        error: ListenerError | None = None

        try:
            if hold is not None:
                hold[1].note_handler_wait(hold[0], listener)

            return await future
        except ListenerError as exc:
            error = exc
            raise
        finally:
            if timer is not None:
                timer.cancel()

            # A cancelled task leaves its future done without running the done callbacks.
            listener.run_done_callbacks()

            if error is not None and (on_error := self.on_error_func) is not None:
                try:
                    await call_maybe_async(on_error, error, listener)
                except Exception:
                    log.exception("Error in on_error_func of the listener for %s", key)

            # The error's traceback keeps this frame: drop what links back to it, so the
            # wait, its message and the client are freed without waiting for the cyclic GC.
            # `current`, the wait this one replaced, would chain every replaced wait.
            del future, listener, error, current, hold

    __call__ = listen
    """Alias of `listen`, so a listener can be awaited as `listener(...)`."""

    async def resolve(self, update: UpdateType) -> bool:
        """Give the update to the waiting listeners it matches, as `resolve_scope` says.

        Only the shapes of the open waits are tried: for each, the update's
        key keeps the fields the shape sets and the `exact` ones, and loses
        the rest. A shape that sets a field the update lacks is skipped. The
        shapes go most fields first, then by field order, so `(chat, user)`
        comes before `(chat, topic)`, which comes before `(chat)`, which
        comes before `(user)`.

        A waiting listener whose filter passes takes the update: with
        `ListenerScope.FIRST` only the first one does, with `ListenerScope.ALL`
        every one does. A listener whose filter fails, or raises (logged), is
        skipped and keeps waiting, or, when `strict`, fails with
        `ListenerRejected`; either way the next candidate is tried. A sync
        filter runs on the client's executor. A wait whose filter failed an
        update skips it if it is offered again, as a `CoordinatedDispatcher`
        does.

        Args:
            update: The incoming Pyrogram update.

        Returns:
            Whether at least one listener took the update.

        Raises:
            TypeError: If `update` is not an instance of `__update_type__`.
        """
        self.validate_update(update)

        # With no wait open, as for most updates of a bot, skip extracting the key.
        if not self.listeners:
            return False

        key = self.extract_key(update)

        if key is None:
            return False

        key_type = self.__key_type__
        names = key_type.key_fields
        values = key.to_tuple()
        present = self._shape_of(values)
        took = False

        for shape in self._shape_order:
            if shape & ~present:
                continue

            keep = shape | self._exact_mask

            kept: dict[str, Any] = {
                name: values[bit] for bit, name in enumerate(names) if keep >> bit & 1
            }

            sub = key_type(**kept)
            listener = self.listeners.get(sub)

            # Declined already: its filter failed this update, offered again from a queue.
            if listener is None or listener.done() or id(update) in listener.declined_updates:
                continue

            if listener.filters is not None:
                try:
                    passed = await call_maybe_async(
                        listener.filters.__call__,
                        update._client,  # ty: ignore[unresolved-attribute]  # Pyrogram sets `_client` on every object in `Object.__init__`
                        update,
                        executor=get_update_executor(update),
                    )
                except Exception:
                    log.exception("Error in the filter of the listener for %s", sub)
                    passed = False

                # The filter may yield; another update or a newer `listen` may have taken the slot.
                if self.listeners.get(sub) is not listener or listener.done():
                    continue

                if not passed:
                    listener.decline(update)

                    if listener.strict:
                        self.reject(sub)
                    continue

            listener.resolve(update)
            took = True

            if self.resolve_scope is ListenerScope.FIRST:
                break

        return took

    def extract_key(self, update: UpdateType) -> ListenerKey[UpdateType] | None:
        """Extract the listener key of the update.

        Args:
            update: The incoming update object.

        Returns:
            The key of the update, or `None` if it should not be listened to.

        Raises:
            TypeError: If `update` is not an instance of `__update_type__`,
                or `extract_key_func` returns something other than exactly a
                `__key_type__` or `None`.

        Example:
            >>> from pyrogram.types import Chat, Message, User
            >>> from pyroflow.update_listener import MessageListener
            >>> update = Message(id=5, chat=Chat(id=1), from_user=User(id=2))
            >>> MessageListener().extract_key(update)
            MessageKey(chat_id=1, user_id=2, message_thread_id=None, direct_messages_topic_id=None, ephemeral=False)
        """
        self.validate_update(update)
        key = self.extract_key_func(update)

        if key is not None and type(key) is not self.__key_type__:
            msg = (
                f"{self.__class__.__name__}.extract_key_func must return exactly a "
                f"{self.__key_type__.__name__} or None, not {type(key).__name__}"
            )
            raise TypeError(msg)

        return key


__all__ = (
    "ListenKw",
    "UpdateListener",
)
