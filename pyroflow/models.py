"""Data models for listeners."""

from __future__ import annotations as _annotations

import asyncio
from dataclasses import Field, dataclass, field, fields, is_dataclass
from itertools import combinations
from typing import Any, ClassVar, TYPE_CHECKING

from pytrove import KeyDefaultDict, classproperty
from pytrove.typings import JsonValue as JsonValueT

if TYPE_CHECKING:
    from collections.abc import Generator


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
    owner_id: str | None = None
    """Owner id the coordinator registered this listener under.

    It tells apart listeners registered under the same key over time, so a
    stale registration or a late loss report never hits the listener that
    replaced this one.
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


__all__ = (
    "ListenerKey",
    "ListenerModel",
)
