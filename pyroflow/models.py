"""Data models for listeners."""

from __future__ import annotations as _annotations

import asyncio
from dataclasses import dataclass, field, fields
from types import SimpleNamespace
from typing import TYPE_CHECKING

from pyrogram.filters import Filter

from .enums import WorkersBusyMode
from .utils import subsets_largest_first

if TYPE_CHECKING:
    from collections.abc import Generator

    from .types import Message


@dataclass(frozen=True, slots=True, eq=True, unsafe_hash=True)
class ListenerKey:
    """Identifies a listener slot: a chat, optionally narrowed to a user and/or a message.

    Example:
        >>> ListenerKey(1, 2) == ListenerKey(chat_id=1, user_id=2, message_id=None)
        True
    """

    chat_id: int
    """The chat the listener waits in."""
    user_id: int | None = None
    """The user the listener waits for, or `None` for any user."""
    message_id: int | None = None
    """The message id the update must carry, or `None` for any message.

    For a message this is the incoming message's own id; for a callback
    query it is the id of the message holding the pressed button.
    """

    def to_tuple(self) -> tuple[int, int | None, int | None]:
        """Return the key's components, in field order.

        Example:
            >>> ListenerKey(1, 2).to_tuple()
            (1, 2, None)
        """
        return tuple(getattr(self, f.name) for f in fields(self))

    def to_dict(self) -> dict[str, int | None]:
        """Return the key's components keyed by field name, in field order.

        Example:
            >>> ListenerKey(1, 2).to_dict()
            {'chat_id': 1, 'user_id': 2, 'message_id': None}
        """
        return {f.name: getattr(self, f.name) for f in fields(self)}

    def sub_keys(self, min_dep: int = 1) -> Generator[ListenerKey, None, None]:
        """Yield every key a listener for this update could be registered under, most specific first.

        `chat_id` is always kept; the other components this key carries are
        combined in every way, so `(chat, None, message)` is reached too. A
        component this key lacks is never added, and no key is yielded twice.
        Between keys of equal size, `user_id` outranks `message_id`.

        Args:
            min_dep: Fewest components to yield down to, counting `chat_id`.
                The default of `1` includes the chat-only key; `2` stops
                before it.

        Raises:
            AssertionError: If `chat_id` is `None`.

        Example:
            >>> for key in ListenerKey(1, 2, 3).sub_keys():
            ...     print(key.to_tuple())
            (1, 2, 3)
            (1, 2, None)
            (1, None, 3)
            (1, None, None)
        """
        if self.chat_id is None:
            msg = "ListenerKey.chat_id must not be None"
            raise AssertionError(msg)

        present = [f.name for f in fields(self)[1:] if getattr(self, f.name) is not None]

        for kept in subsets_largest_first(present):
            if len(kept) + 1 < min_dep:
                return

            yield ListenerKey(self.chat_id, **{name: getattr(self, name) for name in kept})


class ListenerContext(SimpleNamespace):
    """Values attached to a wait: typed base fields, plus any the caller adds.

    Every value, declared or added, is read and set as an attribute. A field
    that is not set reads its class default. Subclass to declare and type
    fields of your own.

    Example:
        >>> class OrderContext(ListenerContext):
        ...     step: int = 0
        >>> context = OrderContext(step=2, note="x")
        >>> context.step, context.note, context.message_id
        (2, 'x', None)
    """

    message_id: int | None = None
    """Id of the message `ask` sent or edited for the wait."""
    message: Message | None = None
    """The message `ask` sent or edited for the wait."""


@dataclass(slots=True)
class ListenerModel:
    """A registered listener: its key, the future its update resolves, its context and filter.

    Example:
        >>> async def main():
        ...     future = asyncio.get_running_loop().create_future()
        ...     listener = ListenerModel(ListenerKey(1), future)
        ...     listener.resolve("update")
        ...     return listener.done(), await listener.future
        >>> asyncio.run(main())
        (True, 'update')
    """

    key: ListenerKey
    """The slot the listener is registered under."""
    future: asyncio.Future
    """Resolved with the matching update, or failed with an error."""
    context: ListenerContext = field(default_factory=ListenerContext)
    """Values attached to the listener."""
    filters: Filter | None = None
    """Pyrogram filter an update must pass besides the key, or `None` for none."""
    strict: bool = False
    """Whether an update that matches the key but fails `filters` ends the wait."""

    def resolve(self, update: object) -> None:
        """Complete the listener's future with `update`."""
        self.future.set_result(update)

    def set_exc(self, exc: Exception) -> None:
        """Fail the listener's future with `exc`."""
        self.future.set_exception(exc)

    def done(self) -> bool:
        """Return whether the listener's future is done."""
        return self.future.done()


@dataclass(frozen=True, slots=True)
class WorkersPolicy:
    """What a wait inside a handler does when the workers run short.

    A handler that waits in `ask` or `listen` holds the worker running it;
    when too many do, no worker is left to read the replies and the bot
    freezes. Once a wait would leave fewer than `free_workers` workers free,
    `mode` steps in, after up to `busy_timeout` seconds for one to free. Set
    it with `Client.with_workers_policy`.

    Raises:
        ValueError: If `free_workers` is below `1`, or `busy_timeout` is negative.

    Example:
        >>> WorkersPolicy(WorkersBusyMode.REJECT, busy_timeout=1).min_free_workers(12)
        4
    """

    mode: WorkersBusyMode = WorkersBusyMode.LEND
    """What steps in; see `WorkersBusyMode` for each mode and when it fits."""
    free_workers: int | None = None
    """Fewest workers a wait may leave free before `mode` steps in; `None` is a third.

    Equal to the client's `workers`, `mode` steps in on every wait: `LEND`
    lends to each, while `REJECT` and `CANCEL_OLDEST` refuse every wait
    inside a handler, since none ever holds a worker.
    """
    busy_timeout: float = 0
    """Seconds to wait first for a worker to free; `0` steps in at once.

    While it waits, that worker reads no update, and the wait is registered
    only afterwards, so an update can slip past it.
    """

    def __post_init__(self) -> None:
        """Check the values; see the class docstring."""
        if self.free_workers is not None and self.free_workers < 1:
            msg = f"free_workers must be at least 1, got {self.free_workers}"
            raise ValueError(msg)

        if self.busy_timeout < 0:
            msg = f"busy_timeout must not be negative, got {self.busy_timeout}"
            raise ValueError(msg)

    def min_free_workers(self, workers: int) -> int:
        """Return how many of `workers` a wait inside a handler must leave free.

        Args:
            workers: The client's number of workers.

        Returns:
            `free_workers`, or a third of `workers` (at least one) when it is `None`.
        """
        if self.free_workers is not None:
            return self.free_workers

        return max(1, workers // 3)


__all__ = (
    "ListenerKey",
    "ListenerContext",
    "ListenerModel",
    "WorkersPolicy",
)
