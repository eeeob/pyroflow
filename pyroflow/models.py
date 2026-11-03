"""Data models for listeners and handled-update records."""

from __future__ import annotations as _annotations

import asyncio
import time
import weakref
from dataclasses import Field, dataclass, field, fields, is_dataclass
from itertools import combinations, count
from typing import Any, ClassVar, TYPE_CHECKING

from pyrogram.handlers import Handler as PyroHandler
from pytrove import KeyDefaultDict, classproperty
from pytrove.typings import JsonValue as JsonValueT, Number

if TYPE_CHECKING:
    from collections.abc import Generator

    # Type-only: `dataclasses` read only `ClassVar` annotations at runtime.
    from .typings import ListenerCoordinatorIdT  # noqa: TC004


# Defined before `ListenerKey`, whose class body passes it to `KeyDefaultDict`.
def _get_plan(mask: int) -> tuple[int, ...]:
    """Return every subset of the bits set in `mask`, largest subsets first.

    Args:
        mask: Bit mask of the optional key components present.

    Returns:
        The subsets as bit masks, ordered by size (descending), then by bit
        position.

    Example:
        >>> _get_plan(0b110)
        (6, 2, 4, 0)
    """
    optional = [i for i in range(mask.bit_length()) if mask >> i & 1]
    plan = []

    for size in range(len(optional), -1, -1):
        for combo in combinations(optional, size):
            keep = 0

            for i in combo:
                keep |= 1 << i

            plan.append(keep)

    return tuple(plan)


@dataclass(frozen=True, slots=True, eq=True, unsafe_hash=True)
class ListenerKey:
    """Identifies a listener slot: a chat, optionally narrowed to a user and/or a message.

    Example:
        >>> ListenerKey(1, 2) == ListenerKey(chat_id=1, user_id=2, message_id=None)
        True
    """

    PLANS: ClassVar[KeyDefaultDict[int, tuple[int, ...]]] = KeyDefaultDict(_get_plan)
    """Cache of `_get_plan` results, keyed by the mask of present optional components."""
    FIELDS: ClassVar[tuple[Field[Any], ...]]
    """The dataclass fields, in declaration order."""

    if not TYPE_CHECKING:

        @classproperty(cached=True)
        def FIELDS(cls) -> tuple[Field[Any], ...]:
            """Return the dataclass fields, in declaration order."""
            if not is_dataclass(cls):
                return cls.__dict__["FIELDS"]
            return fields(cls)

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
        return tuple(getattr(self, f.name) for f in self.FIELDS)

    def to_dict(self) -> dict[str, int | None]:
        """Return the key's components keyed by field name, in field order.

        Example:
            >>> ListenerKey(1, 2).to_dict()
            {'chat_id': 1, 'user_id': 2, 'message_id': None}
        """
        return {f.name: getattr(self, f.name) for f in self.FIELDS}

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
        chat_id, *rest = self.to_tuple()

        if chat_id is None:
            msg = "ListenerKey.chat_id must not be None"
            raise AssertionError(msg)

        mask = 0

        for i, value in enumerate(rest, 1):
            if value is not None:
                mask |= 1 << i

        for keep in ListenerKey.PLANS[mask]:
            if keep.bit_count() + 1 < min_dep:
                return

            yield ListenerKey(
                chat_id, *(value if keep >> i & 1 else None for i, value in enumerate(rest, 1))
            )


@dataclass(slots=True)
class ListenerModel:
    """A registered listener: its key, optional metadata, and the future its update resolves.

    Create it inside a running event loop: the default `future` is bound to it.

    Example:
        >>> async def main():
        ...     listener = ListenerModel(ListenerKey(1))
        ...     listener.resolve("update")
        ...     return listener.done(), await listener.future
        >>> asyncio.run(main())
        (True, 'update')
    """

    key: ListenerKey
    """The slot the listener is registered under."""
    meta: JsonValueT | None = None
    """Optional JSON-serializable metadata attached to the listener."""
    future: asyncio.Future = field(default_factory=asyncio.Future)
    """Resolved with the matching update, or failed with an error."""
    coordinator_id: ListenerCoordinatorIdT | None = None
    """Ownership token handed out by the coordinator at registration time.

    It tells apart listeners registered under the same key over time:
    `UpdateListener.resolve` and `UpdateListener._cancel` compare it so a
    signal still in flight never hits the listener that replaced this one.
    """

    def resolve(self, update: object) -> None:
        """Complete the listener's future with `update`."""
        self.future.set_result(update)

    def set_exc(self, exc: Exception) -> None:
        """Fail the listener's future with `exc`."""
        self.future.set_exception(exc)

    def done(self) -> bool:
        """Return whether the listener's future is done."""
        return self.future.done()


class _WeakSlots:
    """Base that gives a slotted dataclass a `__weakref__` slot."""

    __slots__ = ("__weakref__",)
    """Adds only the `__weakref__` slot so subclass records can be weakly referenced."""


@dataclass(slots=True)
class UpdateRecord(_WeakSlots):
    """A history entry: the handler that handled an update, with optional data; ordered by creation.

    Records with the same `created_at` are ordered by the sequence they were
    created in.

    Example:
        >>> handler = PyroHandler(lambda client, update: None)
        >>> first = UpdateRecord(handler, created_at=1.0)
        >>> second = UpdateRecord(handler, created_at=1.0)
        >>> first < second, second > first
        (True, True)
    """

    _SEQ: ClassVar[count[int]] = count()
    """Counter handing out creation sequence numbers."""
    _SEQ_IDS: ClassVar[dict[int, int]] = {}
    """Sequence number of each live record, keyed by the record's `id()`."""

    handler: PyroHandler
    """The handler that handled the update."""
    data: Any | None = None
    """Optional data stored alongside the record."""
    created_at: Number = field(default_factory=time.time)
    """Creation time, as a Unix timestamp."""

    def __post_init__(self) -> None:
        """Assign the record its creation sequence number, dropped when the record is collected."""
        cls = type(self)
        cls._SEQ_IDS[id(self)] = next(cls._SEQ)
        weakref.finalize(self, cls._SEQ_IDS.pop, id(self), None)

    def __lt__(self, other: UpdateRecord) -> bool:
        """Return whether this record was created before `other`."""
        return (self.created_at, type(self)._SEQ_IDS[id(self)]) < (
            other.created_at,
            type(other)._SEQ_IDS[id(other)],
        )

    def __gt__(self, other: UpdateRecord) -> bool:
        """Return whether this record was created after `other`."""
        return (self.created_at, type(self)._SEQ_IDS[id(self)]) > (
            other.created_at,
            type(other)._SEQ_IDS[id(other)],
        )


__all__ = (
    "ListenerKey",
    "ListenerModel",
    "UpdateRecord",
)
